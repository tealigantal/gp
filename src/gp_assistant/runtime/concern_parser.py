from __future__ import annotations

import re
from typing import Any, Dict

from .context_engine import build_context
from .reference_resolver import inject_entity_hints
from ..contracts.objects import MarketBook, TurnFrame
from ..evidence.live_quote_service import extract_user_quote
from ..llm.interpret import parse_turn_frame


def _clamp_topk(value: int) -> int:
    return max(1, min(value, 10))


def _coerce_topk(value: Any) -> int:
    try:
        return _clamp_topk(int(value))
    except Exception:
        return 3


_RANK_WORDS = {
    "第一": 1,
    "第1": 1,
    "第二": 2,
    "第2": 2,
    "第三": 3,
    "第3": 3,
    "第四": 4,
    "第4": 4,
    "第五": 5,
    "第5": 5,
}


def _rank_from_text(raw: str) -> int | None:
    text = raw or ""
    hits: list[tuple[int, int]] = []
    for key, value in _RANK_WORDS.items():
        pos = text.find(key)
        if pos >= 0:
            hits.append((pos, value))
    if hits:
        return sorted(hits, key=lambda item: item[0])[0][1]
    match = re.search(r"第\s*(\d{1,2})\s*(只|个|名)?", text)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _promote_explain_followups(frame: TurnFrame) -> TurnFrame:
    raw = str(frame.raw_message or "")
    refs = dict(frame.references or {})
    rank = _rank_from_text(raw)
    if rank is not None and refs.get("rank") is None:
        refs["rank"] = rank
    compare_phrases = [
        "不如第一",
        "和第一只比",
        "和上一只比",
        "第一只和第二只",
        "第二只为什么不如第一只",
        "谁更适合",
    ]
    live_phrases = ["现在能买吗", "能不能买", "现在买", "可以买", "能直接买", "能入吗"]
    detail_phrases = [
        "为什么第一只",
        "第二只为什么",
        "触发条件是什么",
        "触发条件",
        "为什么不直接买",
        "为什么这个策略",
        "为什么不是突破策略",
        "风险在哪里",
        "风险在哪",
        "策略为什么",
    ]
    if any(phrase in raw for phrase in compare_phrases):
        frame.request = "compare"
        frame.subject = "compare_set"
    elif any(phrase in raw for phrase in live_phrases):
        frame.request = "live_entry_check"
        frame.subject = "symbol"
    elif _looks_like_live_price_question(raw):
        frame.request = "live_entry_check"
        frame.subject = "symbol"
    elif any(phrase in raw for phrase in detail_phrases):
        frame.request = "pick_detail"
        frame.subject = "pick"
    frame.references = refs
    return frame


def _looks_like_live_price_question(raw: str) -> bool:
    text = str(raw or "")
    has_price_context = any(token in text for token in ("最高", "现价", "现在", "当前", "目前", "稳定", "横盘"))
    has_entry_context = any(token in text for token in ("入场", "能不能", "可不可以", "能买吗", "可以买", "该不该买", "冲"))
    has_number = bool(re.search(r"\d+(?:\.\d+)?", text))
    return bool(has_price_context and has_entry_context and has_number)


def normalize_turn_frame(frame: TurnFrame, book: MarketBook | None = None) -> TurnFrame:
    request_alias = {
        "explain": "pick_detail",
        "live_check": "live_entry_check",
        "exit": "exit_decision",
    }
    freshness_alias = {
        "current_book": "active_run",
        "rebuild_daybook": "rebuild_run",
        "latest_5m": "active_run",
    }
    frame.request = request_alias.get(frame.request, frame.request)
    frame.freshness = freshness_alias.get(frame.freshness, frame.freshness)
    frame.references = frame.references or {}
    frame.constraints = frame.constraints or {}
    frame = _promote_explain_followups(frame)
    frame.references = frame.references or {}
    frame.constraints = frame.constraints or {}
    frame.constraints.setdefault("allow_derived_data", True)
    if frame.request == "live_entry_check":
        quote = extract_user_quote(frame.raw_message)
        if any(quote.get(key) is not None for key in ("current_price", "day_high", "day_low")):
            frame.constraints["user_quote"] = quote
            if quote.get("symbol") and not frame.references.get("symbol"):
                frame.references["symbol"] = quote.get("symbol")
    if frame.request == "recommend":
        frame.constraints["topk"] = _coerce_topk(frame.constraints.get("topk") or 3)
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


def _explicit_symbol_not_in_book(frame: TurnFrame, book: MarketBook) -> bool:
    refs = frame.references or {}
    symbol = str(refs.get("symbol") or "").strip()
    if not symbol or symbol not in str(frame.raw_message or ""):
        return False
    board_symbols = {str(getattr(entry, "symbol", "")).strip() for entry in list(book.board or [])}
    return symbol not in board_symbols


def _promote_external_symbol_query(frame: TurnFrame, book: MarketBook) -> TurnFrame:
    if frame.request in {"pick_detail", "live_entry_check"} and _explicit_symbol_not_in_book(frame, book):
        frame.request = "single_stock_query"
        frame.subject = "symbol"
    return frame


def validate_turn_frame(frame: TurnFrame) -> TurnFrame:
    allowed_requests = {
        "chat",
        "term_explain",
        "recommend",
        "pick_detail",
        "single_stock_query",
        "live_entry_check",
        "no_trade_explain",
        "compare",
        "candidate_compare",
        "intraday_situation",
        "exit_decision",
        "run_change",
    }
    allowed_subjects = {"run", "pick", "symbol", "compare_set", "holding", "market"}
    allowed_freshness = {"active_run", "rebuild_run", "next_session_plan"}
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
    frame = _promote_external_symbol_query(frame, book)
    frame = normalize_turn_frame(frame, book=book)
    return validate_turn_frame(frame)
