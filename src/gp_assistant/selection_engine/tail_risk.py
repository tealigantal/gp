from __future__ import annotations

from typing import Any, Dict


RR_CAP = 8.0
MIN_RISK_PCT = 0.01


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
        if out != out or out in (float("inf"), float("-inf")):
            return None
        return out
    except Exception:
        return None


def effective_reward_risk(
    *,
    price: Any,
    support: Any,
    target: Any,
    atr: Any = None,
    cap: float = RR_CAP,
) -> Dict[str, Any]:
    """Compute capped reward/risk with a volatility-aware risk denominator."""
    px = safe_float(price)
    s1 = safe_float(support)
    r1 = safe_float(target)
    atr_abs = safe_float(atr) or 0.0
    if px is None or s1 is None or r1 is None or px <= 0:
        return {
            "raw": None,
            "effective": None,
            "risk_floor": None,
            "risk_raw": None,
            "capped": False,
        }

    reward = r1 - px
    raw_risk = px - s1
    if reward <= 0 or raw_risk <= 0:
        return {
            "raw": None,
            "effective": None,
            "risk_floor": max(float(atr_abs), px * MIN_RISK_PCT),
            "risk_raw": raw_risk,
            "capped": False,
        }

    risk_floor = max(float(atr_abs), px * MIN_RISK_PCT)
    effective_risk = max(raw_risk, risk_floor, 1e-6)
    raw_rr = reward / max(raw_risk, 1e-6)
    floor_rr = reward / effective_risk
    effective_rr = min(raw_rr, floor_rr, float(cap))
    return {
        "raw": float(raw_rr),
        "effective": float(effective_rr),
        "risk_floor": float(risk_floor),
        "risk_raw": float(raw_risk),
        "capped": bool(effective_rr < raw_rr),
    }
