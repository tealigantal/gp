from __future__ import annotations

from typing import Any, Dict, List

from .feature_vector import vector_similarity
from .store import MarketMemoryEvent, list_events_before


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _prior_block(events: List[MarketMemoryEvent], current_event: MarketMemoryEvent) -> Dict[str, Any]:
    def _ret(event: MarketMemoryEvent) -> float | None:
        outcome = event.outcome or {}
        if outcome.get("complete") is not True:
            return None
        return _safe_float(outcome.get("return_3d"))

    def _summarize(scoped: List[MarketMemoryEvent]) -> Dict[str, Any]:
        values = [value for value in (_ret(event) for event in scoped) if value is not None]
        if not values:
            return {"sample_size": 0, "up_probability_3d": 0.5, "expected_return_3d": 0.0}
        return {
            "sample_size": len(values),
            "up_probability_3d": float(sum(1 for value in values if value > 0.0) / max(1, len(values))),
            "expected_return_3d": float(sum(values) / max(1, len(values))),
        }

    regime = str((current_event.market_context or {}).get("market_regime") or "")
    return {
        "global": _summarize(events),
        "signal": _summarize([event for event in events if event.signal_type == current_event.signal_type]),
        "regime": _summarize(
            [
                event
                for event in events
                if str((event.market_context or {}).get("market_regime") or "") == regime
            ]
        ),
    }


def retrieve_similar_events(
    current_event: MarketMemoryEvent,
    *,
    as_of: str,
    k: int = 80,
    max_pool: int = 4000,
) -> Dict[str, Any]:
    """Retrieve nearest cases by normalized feature-vector distance.

    The primary score is vector similarity. Matching labels can only provide a
    small context adjustment and cannot substitute for vector distance.
    """

    pool = list_events_before(as_of, require_outcome=True, limit=max_pool)
    prior_summary = _prior_block(pool, current_event)
    rows: List[Dict[str, Any]] = []
    current_vec = current_event.feature_vector
    for event in pool:
        base_similarity = vector_similarity(current_vec, event.feature_vector)
        label_adjustment = 0.0
        if event.signal_type == current_event.signal_type:
            label_adjustment += 0.04
        if str((event.market_context or {}).get("market_regime")) == str((current_event.market_context or {}).get("market_regime")):
            label_adjustment += 0.02
        similarity = min(1.0, base_similarity + label_adjustment)
        rows.append(
            {
                "event_id": event.event_id,
                "as_of": event.as_of,
                "symbol": event.symbol,
                "signal_type": event.signal_type,
                "similarity": float(similarity),
                "vector_similarity": float(base_similarity),
                "outcome": dict(event.outcome or {}),
                "features": dict(event.features or {}),
                "market_context": dict(event.market_context or {}),
            }
        )
    rows.sort(key=lambda item: (float(item["similarity"]), float(item["vector_similarity"])), reverse=True)
    nearest = rows[: max(1, int(k))]
    mean_similarity = sum(float(item["similarity"]) for item in nearest) / max(1, len(nearest))
    return {
        "query_event_id": current_event.event_id,
        "query_signal_type": current_event.signal_type,
        "retrieval_method": "normalized_feature_vector_distance",
        "sample_size": len(nearest),
        "mean_similarity": float(mean_similarity),
        "prior_summary": prior_summary,
        "pool_size": len(pool),
        "cases": nearest,
    }
