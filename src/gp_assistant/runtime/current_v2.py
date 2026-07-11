from __future__ import annotations

import math
from typing import Any

from ..contracts.objects import BoardEntry, MarketBook
from ..intraday.plans import NON_EXECUTION_PHASES


def _score(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except Exception:
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if number > 1.0:
        number /= 100.0
    return max(0.0, min(1.0, number))


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _first_present(*values: Any) -> Any:
    return next((value for value in values if value is not None), None)


def _entry_zone(entry: BoardEntry) -> list[float]:
    raw = dict(entry.entry_zone or entry.pick.entry_plan or {})
    values = [_positive(raw.get(key)) for key in ("low", "high")]
    return [value for value in values if value is not None]


def _execution_state(entry: BoardEntry, *, actionable: bool) -> str:
    state = str(entry.recommendation_state or "").upper()
    if entry.invalidated:
        return "breakdown_risk"
    if actionable:
        return "actionable"
    if state in {"TRIGGER_PLAN", "NEXT_SESSION_PLAN", "TRADING_SIGNAL"}:
        return "waiting_pullback"
    return "observe_only"


def _item(entry: BoardEntry, *, run_id: str, publish_allowed: bool) -> dict[str, Any]:
    state = str(entry.recommendation_state or "").upper()
    actionable = bool(publish_allowed and entry.can_open and not entry.invalidated and state == "TRADING_SIGNAL")
    adaptive = dict(entry.pick.explain_context.get("adaptive_policy") or entry.pick.meta.get("adaptive_policy") or {})
    probability = dict(entry.pick.probability or {})
    risk = dict(entry.pick.risk or {})
    execution = dict(entry.execution_plan or {})
    final_score = _score(adaptive.get("decision_score") if adaptive.get("decision_score") is not None else entry.final_score)
    invalidation = risk.get("invalidation") or entry.pick.why_not_others or []
    if isinstance(invalidation, str):
        invalidation = [invalidation]
    return {
        "pick_id": f"{run_id}:{entry.symbol}",
        "symbol": entry.symbol,
        "name": entry.name,
        "rank": entry.rank,
        "strategy": entry.champion_strategy or entry.pick.meta.get("strategy_id"),
        "strategy_label": entry.champion_strategy or entry.pick.style_label,
        "thesis": entry.pick.thesis or entry.pick.why_selected or entry.summary,
        "entry_zone": _entry_zone(entry),
        "stop": _positive(entry.stop),
        "take_profit": [value for value in (_positive(item) for item in entry.take) if value is not None],
        "reward_risk": _positive(execution.get("rr_to_take1") or (risk.get("diagnostics") or {}).get("reward_risk")),
        "execution_state": _execution_state(entry, actionable=actionable),
        "recommendation_state": entry.recommendation_state,
        "actionable": actionable,
        "invalidated_now": bool(entry.invalidated),
        "risk_flags": list(entry.pick.risk_flags or []),
        "invalidation": list(invalidation),
        "final_score": final_score,
        "adaptive_score": _score(adaptive.get("adaptive_score") if adaptive.get("adaptive_score") is not None else final_score),
        "calibrated_probability": _score(_first_present(adaptive.get("calibrated_probability"), probability.get("up_probability_3d"))),
        "confidence": _score(_first_present(adaptive.get("confidence"), probability.get("confidence"))),
        "execution_score": _score(entry.exec_score),
        "alpha_score": final_score,
        "reliability_score": _score(_first_present(adaptive.get("feature_coverage"), 1.0)),
        "reason_codes": list(entry.reason_codes or []),
        "artifact_id": entry.artifact_id,
        "decision_context_snapshot_id": entry.pick.decision_context_snapshot_id,
    }


def current_book_to_v2(book: MarketBook | None) -> dict[str, Any]:
    if book is None:
        return {
            "artifact_version": "v2",
            "source": "current_book",
            "run_id": None,
            "as_of": None,
            "degraded": True,
            "tradeable": False,
            "reason": "current_book_unavailable",
            "symbols": [],
            "themes": [],
            "items": [],
            "fallback_used": False,
        }
    run_id = str(book.artifact_id or book.book_version)
    items = [_item(entry, run_id=run_id, publish_allowed=bool(book.publish_allowed)) for entry in book.board]
    non_trading = str(book.market_phase or "").upper() in NON_EXECUTION_PHASES
    freshness = dict(book.daybook.source_meta.get("daily_freshness") or {})
    return {
        "artifact_version": "v2",
        "source": "current_book",
        "run_id": run_id,
        "as_of": book.updated_at,
        "snapshot_id": book.daybook.source_meta.get("decision_context_snapshot_id"),
        "artifact_id": book.artifact_id,
        "book_version": book.book_version,
        "trading_day": book.trading_day,
        "daybook_effective_day": book.daybook_effective_day,
        "market_phase": book.market_phase,
        "slot_status": book.slot_status,
        "publish_allowed": bool(book.publish_allowed),
        "non_trading": non_trading,
        "data_status": book.data_status,
        "freshness": freshness,
        "degraded": not bool(book.data_quality.complete),
        "tradeable": bool(book.publish_allowed),
        "reason": book.daybook.reason,
        "symbols": [item["symbol"] for item in items],
        "themes": list(book.daybook.themes or []),
        "items": items,
        "fallback_used": False,
    }
