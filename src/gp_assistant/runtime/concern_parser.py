from __future__ import annotations

from typing import Any, Dict

from .context_engine import build_context
from .reference_resolver import inject_entity_hints
from ..contracts.objects import MarketBook, TurnFrame
from ..core.config import load_config
from ..llm.interpret import parse_turn_frame


def _intraday_runtime_enabled() -> bool:
    return bool(getattr(load_config(), "intraday_runtime_enabled", False))


def _clamp_topk(value: int) -> int:
    return max(1, min(value, 10))


def _coerce_topk(value: Any) -> int:
    try:
        return _clamp_topk(int(value))
    except Exception:
        return 3


def normalize_turn_frame(frame: TurnFrame, book: MarketBook | None = None) -> TurnFrame:
    request_alias = {
        "explain": "pick_detail",
        "live_check": "live_entry_check",
        "exit": "exit_decision",
    }
    freshness_alias = {
        "current_book": "active_run",
        "rebuild_daybook": "rebuild_run",
    }
    frame.request = request_alias.get(frame.request, frame.request)
    frame.freshness = freshness_alias.get(frame.freshness, frame.freshness)
    frame.references = frame.references or {}
    frame.constraints = frame.constraints or {}
    frame.constraints.setdefault("allow_derived_data", True)
    if frame.request == "recommend":
        frame.constraints["topk"] = _coerce_topk(frame.constraints.get("topk") or 3)
    if frame.request == "live_entry_check" and frame.freshness == "active_run" and _intraday_runtime_enabled():
        frame.freshness = "latest_5m"
    if not _intraday_runtime_enabled() and frame.freshness == "latest_5m":
        frame.freshness = "active_run"
    if (
        frame.request == "recommend"
        and frame.freshness == "active_run"
        and book is not None
        and str(book.market_phase or "").upper()
        in {"POSTCLOSE_PENDING", "POSTCLOSE_READY", "PREOPEN", "OPEN_NO_FIRST_BAR", "NON_TRADING"}
    ):
        frame.freshness = "next_session_plan"
    ambiguity = frame.ambiguity or {}
    try:
        confidence = float(ambiguity.get("confidence", 0.5))
    except Exception:
        confidence = 0.5
    ambiguity["confidence"] = max(0.0, min(1.0, confidence))
    notes = ambiguity.get("notes")
    ambiguity["notes"] = [str(item) for item in notes] if isinstance(notes, list) else []
    ambiguity["needs_clarification"] = bool(ambiguity.get("needs_clarification", False))
    frame.ambiguity = ambiguity
    return frame


def _validate_intent(frame: TurnFrame, memory_ctx: Dict[str, Any]) -> TurnFrame:
    refs = frame.references or {}
    session = memory_ctx["session"]
    focus_symbol = refs.get("focus_symbol") or getattr(session, "last_focus_symbol", None)

    if frame.request in {"pick_detail", "live_entry_check", "exit_decision"}:
        if not any(refs.get(key) for key in ("symbol", "rank")) and focus_symbol:
            refs["symbol"] = focus_symbol
    if frame.request == "compare" and not refs.get("compare_symbols"):
        symbol = refs.get("symbol")
        if symbol:
            refs["compare_symbols"] = [symbol]
    if frame.request == "no_trade_explain" and refs.get("symbol"):
        frame.subject = "symbol"
    frame.references = refs
    return frame


def validate_turn_frame(frame: TurnFrame) -> TurnFrame:
    allowed_requests = {
        "chat",
        "term_explain",
        "recommend",
        "pick_detail",
        "live_entry_check",
        "no_trade_explain",
        "compare",
        "exit_decision",
        "run_change",
    }
    allowed_subjects = {"run", "pick", "symbol", "compare_set", "holding", "market"}
    allowed_freshness = {"active_run", "latest_5m", "rebuild_run", "next_session_plan"}
    if frame.request not in allowed_requests:
        raise ValueError(f"Illegal request: {frame.request}")
    if frame.subject not in allowed_subjects:
        raise ValueError(f"Illegal subject: {frame.subject}")
    if frame.freshness not in allowed_freshness:
        raise ValueError(f"Illegal freshness: {frame.freshness}")
    return frame


def parse_concern(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    context = build_context(memory_ctx, book)
    frame = parse_turn_frame(context, user_message)
    frame = normalize_turn_frame(frame, book=book)
    frame = inject_entity_hints(frame, memory_ctx, book)
    frame = _validate_intent(frame, memory_ctx)
    frame = normalize_turn_frame(frame, book=book)
    return validate_turn_frame(frame)
