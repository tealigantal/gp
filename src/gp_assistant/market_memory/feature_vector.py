from __future__ import annotations

from math import exp, sqrt
from typing import Any, Dict, Iterable, List, Mapping


FEATURE_KEYS: tuple[str, ...] = (
    "trend_strength",
    "pullback_quality",
    "volume_confirmation",
    "atr_pct",
    "extension_pct",
    "support_distance_pct",
    "liquidity_score",
    "market_regime_score",
    "industry_strength_score",
    "price_position_score",
)

FEATURE_WEIGHTS: dict[str, float] = {
    "trend_strength": 1.25,
    "pullback_quality": 1.15,
    "volume_confirmation": 1.0,
    "atr_pct": 0.85,
    "extension_pct": 0.9,
    "support_distance_pct": 0.9,
    "liquidity_score": 0.6,
    "market_regime_score": 0.85,
    "industry_strength_score": 0.55,
    "price_position_score": 0.95,
}


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


def _scale(value: Any, *, lo: float, hi: float, default: float = 0.0) -> float:
    raw = _safe_float(value, default)
    if hi <= lo:
        return _clamp(raw)
    return _clamp((raw - lo) / (hi - lo))


def build_feature_vector(features: Mapping[str, Any]) -> Dict[str, float]:
    """Normalize raw signal features into a stable vector used for retrieval.

    Similarity retrieval must consume this numeric vector. Categorical labels
    such as signal_type or regime are intentionally not part of the vector and
    cannot replace vector distance.
    """

    trend = _clamp(_safe_float(features.get("trend_strength")))
    pullback = _clamp(_safe_float(features.get("pullback_quality")))
    volume = _scale(features.get("volume_ratio", features.get("volume_confirmation")), lo=0.0, hi=3.0)
    atr = _scale(features.get("atr_pct"), lo=0.0, hi=0.10)
    extension = _scale(features.get("extension_pct"), lo=-0.20, hi=0.20, default=0.0)
    support_distance = _scale(features.get("support_distance_pct"), lo=0.0, hi=0.20)
    liquidity = _clamp(_safe_float(features.get("liquidity_score"), 0.5))
    regime = _clamp(_safe_float(features.get("market_regime_score"), 0.5))
    industry = _clamp(_safe_float(features.get("industry_strength_score"), 0.5))
    price_position = _clamp(_safe_float(features.get("price_position_score"), 0.5))
    return {
        "trend_strength": trend,
        "pullback_quality": pullback,
        "volume_confirmation": volume,
        "atr_pct": atr,
        "extension_pct": extension,
        "support_distance_pct": support_distance,
        "liquidity_score": liquidity,
        "market_regime_score": regime,
        "industry_strength_score": industry,
        "price_position_score": price_position,
    }


def vector_distance(left: Mapping[str, Any], right: Mapping[str, Any], *, keys: Iterable[str] = FEATURE_KEYS) -> float:
    total = 0.0
    weight_total = 0.0
    for key in keys:
        weight = float(FEATURE_WEIGHTS.get(key, 1.0))
        lv = _safe_float(left.get(key), 0.0)
        rv = _safe_float(right.get(key), 0.0)
        total += weight * (lv - rv) * (lv - rv)
        weight_total += weight
    if weight_total <= 0:
        return 0.0
    return sqrt(total / weight_total)


def vector_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    distance = vector_distance(left, right)
    return _clamp(exp(-2.4 * distance))


def vector_to_list(vector: Mapping[str, Any]) -> List[float]:
    return [_safe_float(vector.get(key), 0.0) for key in FEATURE_KEYS]
