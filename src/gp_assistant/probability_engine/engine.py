from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any, Dict, Iterable, List


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


def _effective_sample(weights: Iterable[float]) -> float:
    values = [max(0.0, float(w)) for w in weights]
    total = sum(values)
    sq = sum(w * w for w in values)
    if total <= 0.0 or sq <= 0.0:
        return 0.0
    return (total * total) / sq


def _weighted_mean(values: List[float], weights: List[float], default: float = 0.0) -> float:
    total_w = sum(weights)
    if total_w <= 0.0 or not values:
        return default
    return sum(v * w for v, w in zip(values, weights)) / total_w


def _distribution(values: List[float]) -> Dict[str, int]:
    return {
        "strong_loss": sum(1 for value in values if value <= -0.03),
        "loss": sum(1 for value in values if -0.03 < value < 0.0),
        "small_gain": sum(1 for value in values if 0.0 <= value < 0.03),
        "strong_gain": sum(1 for value in values if value >= 0.03),
    }


def _failure_modes(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    counter: Counter[str] = Counter()
    for case in cases:
        outcome = case.get("outcome") or {}
        for mode in outcome.get("failure_modes") or []:
            text = str(mode or "").strip()
            if text:
                counter[text] += 1
        if outcome.get("stop_hit") is True:
            counter["stop_hit"] += 1
    return [{"mode": mode, "count": count} for mode, count in counter.most_common(5)]


def _prior_probability(
    cases: List[Dict[str, Any]],
    current_signal_type: str | None,
    current_regime: str | None,
    retrieval: Dict[str, Any],
) -> Dict[str, Any]:
    prior_summary = retrieval.get("prior_summary") if isinstance(retrieval.get("prior_summary"), dict) else {}
    global_block = prior_summary.get("global") if isinstance(prior_summary.get("global"), dict) else {}
    signal_block = prior_summary.get("signal") if isinstance(prior_summary.get("signal"), dict) else {}
    regime_block = prior_summary.get("regime") if isinstance(prior_summary.get("regime"), dict) else {}
    if int(global_block.get("sample_size") or 0) > 0:
        global_p = _clamp(_safe_float(global_block.get("up_probability_3d"), 0.5))
        signal_p = _clamp(_safe_float(signal_block.get("up_probability_3d"), global_p))
        regime_p = _clamp(_safe_float(regime_block.get("up_probability_3d"), global_p))
        prior = 0.50 * global_p + 0.30 * signal_p + 0.20 * regime_p
        return {
            "global_up_probability_3d": float(global_p),
            "signal_up_probability_3d": float(signal_p),
            "regime_up_probability_3d": float(regime_p),
            "blended_prior_up_probability_3d": float(prior),
            "global_sample_size": int(global_block.get("sample_size") or 0),
            "signal_sample_size": int(signal_block.get("sample_size") or 0),
            "regime_sample_size": int(regime_block.get("sample_size") or 0),
            "source": "market_memory_pool",
        }
    returns_all = [_safe_float((case.get("outcome") or {}).get("return_3d")) for case in cases]
    global_success = [value for value in returns_all if value != 0.0]
    global_p = sum(1 for value in global_success if value > 0.0) / max(1, len(global_success))
    signal_cases = [
        _safe_float((case.get("outcome") or {}).get("return_3d"))
        for case in cases
        if str(case.get("signal_type") or "") == str(current_signal_type or "")
    ]
    signal_p = sum(1 for value in signal_cases if value > 0.0) / max(1, len(signal_cases)) if signal_cases else global_p
    regime_cases = [
        _safe_float((case.get("outcome") or {}).get("return_3d"))
        for case in cases
        if str((case.get("market_context") or {}).get("market_regime") or "") == str(current_regime or "")
    ]
    regime_p = sum(1 for value in regime_cases if value > 0.0) / max(1, len(regime_cases)) if regime_cases else global_p
    prior = 0.50 * global_p + 0.30 * signal_p + 0.20 * regime_p
    return {
        "global_up_probability_3d": float(global_p),
        "signal_up_probability_3d": float(signal_p),
        "regime_up_probability_3d": float(regime_p),
        "blended_prior_up_probability_3d": float(prior),
        "global_sample_size": len(global_success),
        "signal_sample_size": len(signal_cases),
        "regime_sample_size": len(regime_cases),
        "source": "nearest_cases_fallback",
    }


def infer_probability(*, current_event: Dict[str, Any], retrieval: Dict[str, Any]) -> Dict[str, Any]:
    cases = list(retrieval.get("cases") or [])
    current_signal_type = str(current_event.get("signal_type") or "")
    current_regime = str((current_event.get("market_context") or {}).get("market_regime") or "")
    weights = [_clamp(_safe_float(case.get("similarity"))) for case in cases]
    returns_1d = [_safe_float((case.get("outcome") or {}).get("return_1d")) for case in cases]
    returns_3d = [_safe_float((case.get("outcome") or {}).get("return_3d")) for case in cases]
    drawdowns = [abs(min(0.0, _safe_float((case.get("outcome") or {}).get("max_drawdown")))) for case in cases]
    successes = [1.0 if value > 0.0 else 0.0 for value in returns_3d]
    stop_hits = [1.0 if bool((case.get("outcome") or {}).get("stop_hit") is True) else 0.0 for case in cases]
    weighted_success = _weighted_mean(successes, weights, default=0.5)
    expected_return = _weighted_mean(returns_3d, weights, default=0.0)
    drawdown_probability_nn = _weighted_mean(stop_hits, weights, default=0.5)
    expected_drawdown = _weighted_mean(drawdowns, weights, default=0.03)
    effective_n = _effective_sample(weights)
    prior = _prior_probability(cases, current_signal_type, current_regime, retrieval)
    prior_strength = 20.0
    prior_p = _safe_float(prior.get("blended_prior_up_probability_3d"), 0.5)
    posterior_p = (weighted_success * effective_n + prior_p * prior_strength) / max(1.0, effective_n + prior_strength)
    uncertainty = sqrt(max(0.0, posterior_p * (1.0 - posterior_p)) / max(1.0, effective_n + prior_strength))
    mean_similarity = _safe_float(retrieval.get("mean_similarity"))
    uncertainty = min(0.50, uncertainty + max(0.0, 0.70 - mean_similarity) * 0.20)
    confidence = _clamp((effective_n / 80.0) * 0.65 + mean_similarity * 0.35)
    evidence = {
        "retrieval_method": retrieval.get("retrieval_method"),
        "sample_size": len(cases),
        "effective_sample_size": float(effective_n),
        "mean_similarity": float(mean_similarity),
        "pool_size": int(retrieval.get("pool_size") or len(cases)),
        "success_distribution": _distribution(returns_3d),
        "failure_distribution": {
            "stop_hit": sum(1 for value in stop_hits if value > 0.0),
            "negative_1d": sum(1 for value in returns_1d if value < 0.0),
            "negative_3d": sum(1 for value in returns_3d if value < 0.0),
        },
        "major_failure_modes": _failure_modes(cases),
        "priors": prior,
        "nearest_cases": cases[:8],
    }
    return {
        "up_probability_3d": float(_clamp(posterior_p)),
        "expected_return_3d": float(expected_return),
        "drawdown_probability": float(_clamp(drawdown_probability_nn)),
        "expected_max_drawdown": float(expected_drawdown),
        "uncertainty": float(uncertainty),
        "confidence": float(confidence),
        "evidence": evidence,
    }
