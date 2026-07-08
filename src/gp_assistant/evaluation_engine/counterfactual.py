from __future__ import annotations

from typing import Any, Dict, List


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def classify_prediction_error(*, prediction: Dict[str, Any], outcome: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    ret3 = _safe_float(outcome.get("return_3d"))
    predicted_p = _safe_float(prediction.get("up_probability_3d"), 0.5)
    drawdown = abs(min(0.0, _safe_float(outcome.get("max_drawdown"))))
    predicted_drawdown = _safe_float(prediction.get("drawdown_probability"), 0.0)
    evidence = prediction.get("evidence") or {}
    if ret3 < 0 and predicted_p >= 0.58:
        errors.append("wrong_signal")
    if drawdown >= 0.04 and predicted_drawdown < 0.30:
        errors.append("risk_estimation_failure")
    if float(evidence.get("effective_sample_size") or 0.0) < 30 and predicted_p >= 0.55:
        errors.append("low_sample_overconfidence")
    if outcome.get("stop_hit") is True:
        errors.append("execution_failure")
    return errors or (["market_regime_change"] if ret3 < 0 else [])


def analyze_regret(*, selected: List[Dict[str, Any]], alternatives: List[Dict[str, Any]]) -> Dict[str, Any]:
    selected_returns = [_safe_float((item.get("outcome") or {}).get("return_3d")) for item in selected]
    alt_returns = [_safe_float((item.get("outcome") or {}).get("return_3d")) for item in alternatives]
    selected_best = max(selected_returns) if selected_returns else 0.0
    alt_best = max(alt_returns) if alt_returns else 0.0
    return {
        "selected_best_return_3d": selected_best,
        "alternative_best_return_3d": alt_best,
        "regret": max(0.0, alt_best - selected_best),
        "alternative_count": len(alternatives),
    }
