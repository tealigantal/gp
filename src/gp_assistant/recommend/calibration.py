from __future__ import annotations

"""
Centralized calibration for Phase 2 three-part scoring.

alpha_score: opportunity quality (based on deterministic inputs)
execution_score: executability at current time (reward_risk/state)
reliability_score: confidence (degraded/data completeness/liquidity/freshness)

Notes for Phase 2.6 hardening:
- Scoring must rely only on V2 item explicit fields and/or an internal
  basis container ("_score_inputs"), not on v1 sub-structures like
  champion/trade_plan/diagnostics which are not present on V2 artifacts.

All thresholds/constants live here to avoid scattering.
"""

from typing import Any, Dict


# --- Named constants (documented for gating and calibration) ---
ALPHA_CHAMPION_SCALE = 1.5          # champ_score / scale -> [0, ~]
EXEC_RR_SATURATE = 2.0              # reward_risk capped contribution
# keep constants but avoid saturating actionable branch
EXEC_ACTIONABLE_BONUS = 0.0         # no direct additive bonus to avoid saturation
EXEC_WAITING_BASE = 0.5
EXEC_OBSERVE_BASE = 0.2
EXEC_BELOW_BASE = 0.0
RELY_DEGRADED_PENALTY = 0.4
RELY_LIQ = {"A": 1.0, "B": 0.75, "C": 0.5}
RELY_MIN = 0.2

# No-trade gating thresholds
GATE_MIN_ITEMS = 1
GATE_MIN_ACTIONABLE_RATIO = 0.2
GATE_MIN_EXEC_SCORE_MEAN = 0.45


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def calibrate_item_scores(item: Dict[str, Any], *, degraded: bool = False) -> Dict[str, float]:
    """
    Compute scores using only V2-available inputs.

    Inputs used:
    - item["execution_state"], item["reward_risk"]
    - item["liquidity_grade"]
    - optional internal basis from item["_score_inputs"], including
      champion_score_raw (for alpha proxy) and reward_risk_raw fallback.
    """
    basis = (item.get("_score_inputs") or {}) if isinstance(item, dict) else {}

    # alpha: simple conservative squash from champion_score_raw when present
    champ_score = 0.0
    try:
        champ_score = float(basis.get("champion_score_raw") or 0.0)
    except Exception:
        champ_score = 0.0
    alpha = _clamp01(max(0.0, champ_score / ALPHA_CHAMPION_SCALE))

    # execution: base from V2 execution_state + reward_risk
    state = str(item.get("execution_state") or "")
    rr = 0.0
    try:
        rr = float(item.get("reward_risk") if item.get("reward_risk") is not None else (basis.get("reward_risk_raw") or 0.0))
    except Exception:
        rr = 0.0
    # Reward/risk contributes headroom without saturating actionable items
    rr_contrib = min(0.4, max(0.0, rr / EXEC_RR_SATURATE))
    base = EXEC_OBSERVE_BASE
    if state == "actionable":
        # Leave headroom so rr still differentiates actionable items
        base = 0.5
    elif state == "waiting_pullback":
        # Slightly below actionable baseline
        base = min(EXEC_WAITING_BASE, 0.45)
    elif state in {"below_support", "breakdown_risk"}:
        base = EXEC_BELOW_BASE
    exec_score = _clamp01(base + rr_contrib)

    # reliability: degraded penalty + liquidity floor
    liq = str(item.get("liquidity_grade") or "")
    liq_part = RELY_LIQ.get(liq, 0.6)
    rel = liq_part - (RELY_DEGRADED_PENALTY if degraded else 0.0)
    rel = max(RELY_MIN, min(1.0, rel))

    # final fused (ensure ordering compliance)
    final = _clamp01(0.45 * exec_score + 0.35 * alpha + 0.20 * rel)
    return {
        "alpha_score": alpha,
        "execution_score": exec_score,
        "reliability_score": rel,
        "final_score": final,
        "confidence": rel,
    }


def apply_scores_to_v2_item(item: Dict[str, Any], *, degraded: bool = False) -> None:
    sc = calibrate_item_scores(item, degraded=degraded)
    for k, v in sc.items():
        item[k] = v


def compute_no_trade_gate(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """
    Decide top-level tradeability and reason using centralized thresholds.
    """
    try:
        items = artifact.get("items") or []
        n = len(items)
        if n < GATE_MIN_ITEMS:
            return {"tradeable": False, "reason": "候选为空"}
        actives = [it for it in items if bool(it.get("actionable") is True)]
        exec_mean = 0.0
        try:
            exec_scores = [float(it.get("execution_score") or 0.0) for it in items]
            exec_mean = sum(exec_scores) / max(1, len(exec_scores))
        except Exception:
            exec_mean = 0.0
        if (len(actives) / max(1, n)) < GATE_MIN_ACTIONABLE_RATIO:
            return {"tradeable": False, "reason": "当前候选整体执行性不足，建议观望"}
        if exec_mean < GATE_MIN_EXEC_SCORE_MEAN:
            return {"tradeable": False, "reason": "当前候选整体执行性不足，建议观望"}
        return {"tradeable": True}
    except Exception:
        return {"tradeable": False, "reason": "评估失败"}
