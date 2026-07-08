from __future__ import annotations

from typing import Any, Dict


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if value < lo else hi if value > hi else value


def assess_candidate_risk(*, signal: Dict[str, Any], probability: Dict[str, Any]) -> Dict[str, Any]:
    features = dict(signal.get("features") or {})
    close = _safe_float(features.get("close"))
    atr_pct = max(0.012, _safe_float(features.get("atr_pct"), 0.03))
    support = _safe_float(features.get("support"), close * (1.0 - atr_pct))
    expected_return = _safe_float(probability.get("expected_return_3d"))
    drawdown_probability = _safe_float(probability.get("drawdown_probability"), 0.5)
    confidence = _safe_float(probability.get("confidence"), 0.0)
    pullback_quality = _safe_float(features.get("pullback_quality"), 0.5)
    volume_confirmation = min(1.0, _safe_float(features.get("volume_ratio"), 1.0) / 2.5)
    liquidity = _safe_float(features.get("liquidity_score"), 0.5)
    execution_quality = _clamp(0.35 * pullback_quality + 0.25 * volume_confirmation + 0.20 * liquidity + 0.20 * confidence)
    stop_pct = max(0.03, atr_pct * 1.35)
    target_pct = max(0.025, min(0.12, max(expected_return, atr_pct * 1.4)))
    if close <= 0:
        entry = {"kind": "unavailable"}
        stop = {"kind": "unavailable"}
        take = {"kind": "unavailable", "targets": []}
    else:
        low = max(0.01, min(close, support if support > 0 else close * (1.0 - atr_pct)))
        high = max(low, close * 1.01)
        entry = {"kind": "zone", "low": low, "high": high, "price": low}
        stop = {
            "kind": "close_below_support",
            "price": close * (1.0 - stop_pct),
            "text": "收盘有效跌破相似事件风险边界",
            "invalidation": "收盘有效跌破相似事件风险边界",
        }
        take = {"kind": "targets", "price": close * (1.0 + target_pct), "targets": [close * (1.0 + target_pct)]}
    risk_flags: list[str] = []
    if drawdown_probability >= 0.45:
        risk_flags.append("drawdown_probability_high")
    if confidence < 0.35:
        risk_flags.append("low_probability_confidence")
    if execution_quality < 0.45:
        risk_flags.append("execution_quality_low")
    if _safe_float(probability.get("uncertainty"), 0.5) >= 0.18:
        risk_flags.append("probability_uncertainty_high")
    return {
        "execution_quality": float(execution_quality),
        "risk_adjustment": float(_clamp(1.0 - drawdown_probability)),
        "drawdown_probability": float(drawdown_probability),
        "expected_max_drawdown": float(_safe_float(probability.get("expected_max_drawdown"), stop_pct)),
        "risk_flags": risk_flags,
        "entry": entry,
        "stop": stop,
        "take_profit": take,
        "diagnostics": {
            "execution_state": "actionable" if execution_quality >= 0.55 and not risk_flags else "observe_only",
            "actionable": bool(execution_quality >= 0.55 and not risk_flags),
            "reward_risk": float(target_pct / max(stop_pct, 1e-6)),
        },
        "failure_modes": list((probability.get("evidence") or {}).get("major_failure_modes") or []),
    }


def rank_candidate(*, probability: Dict[str, Any], risk: Dict[str, Any]) -> Dict[str, Any]:
    expected_return = _safe_float(probability.get("expected_return_3d"))
    win_probability = _safe_float(probability.get("up_probability_3d"), 0.5)
    execution_quality = _safe_float(risk.get("execution_quality"), 0.0)
    confidence = _safe_float(probability.get("confidence"), 0.0)
    risk_adjustment = _safe_float(risk.get("risk_adjustment"), 0.0)
    positive_edge = max(0.0, expected_return)
    ranking_score = positive_edge * win_probability * execution_quality * confidence * risk_adjustment
    return {
        "ranking_score": float(ranking_score),
        "ranking_factors": {
            "expected_return_3d": expected_return,
            "win_probability_3d": win_probability,
            "execution_quality": execution_quality,
            "confidence": confidence,
            "risk_adjustment": risk_adjustment,
        },
        "rankable": bool(ranking_score > 0.0),
    }
