from __future__ import annotations

import re
from typing import Any, Dict

from .context_engine import build_context
from .reference_resolver import inject_entity_hints
from ..contracts.objects import MarketBook, TurnFrame
from ..llm.interpret import parse_turn_frame
from ..runtime.utils import gen_id

_SYMBOL_RE = re.compile(r"(?<!\d)(?:60|68|00|30)\d{4}(?!\d)")
_ARABIC_RANK_RE = re.compile(r"第\s*(\d{1,2})\s*(?:只|个|名|票)?")
_TOPK_REQUEST_RE = re.compile(r"(?:推荐|给我|看看|来个).{0,8}?(\d{1,2}|一|二|三|四|五|六|七|八|九|十)\s*(?:只|个|票|标的)?")
_REFRESH_WORDS = ("重新", "刷新", "再看", "重跑", "更新")
_POSTCLOSE_WORDS = ("收盘", "盘后", "明天开盘前", "非交易", "下一交易窗口")
_LIVE_WORDS = ("现在还能买吗", "还能冲吗", "现在能不能上", "这个位置还能进吗", "盘中", "等回踩", "现在是不是先别追")
_NO_TRADE_WORDS = ("不太适合做", "先别动", "为什么建议空仓", "今天没票是为什么", "风险大不大", "今天是不是不太适合做")
_EXIT_WORDS = ("该不该卖", "要不要止损", "到目标了要不要减", "还能拿吗", "是不是该走了", "减仓", "卖出")
_COMPARE_WORDS = ("比较", "对比", "哪个好", "哪个更强", "谁更稳", "为什么第二个不是第一个")
_RUN_CHANGE_WORDS = ("为什么这次和上次不一样", "之前那只怎么没了", "为什么榜单变了", "上次推荐", "这次为什么不在")
_DETAIL_WORDS = ("为什么", "逻辑是什么", "止盈止损点", "风控怎么看", "支撑压力在哪", "为什么能上榜", "入选理由")
_DECISION_BASIS_WORDS = ("怎么得出的", "怎么得出来的", "怎么来的", "依据是什么", "为什么这么判断", "怎么判断的")
_TERM_EXPLAIN_WORDS = ("什么是", "什么意思", "这句话什么意思", "为什么仅观察", "为什么只观察", "为什么进观察", "为什么是观察")
_CHAT_WORDS = ("你好", "您好", "help", "你是谁", "怎么用")
_ZH_NUMBER_MAP = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}
_ZH_RANK_MAP = {
    "第一": 1,
    "第二": 2,
    "第三": 3,
    "第四": 4,
    "第五": 5,
    "第六": 6,
    "第七": 7,
    "第八": 8,
    "第九": 9,
    "第十": 10,
}


def _contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _clamp_topk(value: int) -> int:
    return max(1, min(value, 10))


def _parse_topk(text: str) -> int | None:
    match = _TOPK_REQUEST_RE.search(text)
    if not match:
        return None
    token = match.group(1).strip()
    if token.isdigit():
        return _clamp_topk(int(token))
    return _ZH_NUMBER_MAP.get(token)


def _parse_rank(text: str) -> int | None:
    for token, rank in _ZH_RANK_MAP.items():
        if token in text:
            return rank
    match = _ARABIC_RANK_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _fallback_frame(
    user_message: str,
    *,
    subject: str,
    request: str,
    freshness: str,
    references: Dict[str, Any] | None = None,
    constraints: Dict[str, Any] | None = None,
    confidence: float = 0.8,
    note: str = "fallback parse",
) -> TurnFrame:
    return TurnFrame.model_validate(
        {
            "frame_id": gen_id("frame"),
            "raw_message": user_message,
            "subject": subject,
            "request": request,
            "freshness": freshness,
            "references": references or {},
            "constraints": {"allow_derived_data": True, **(constraints or {})},
            "ambiguity": {"confidence": confidence, "notes": [note], "needs_clarification": False},
        }
    )


def _fallback_semantic_parse(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    msg = (user_message or "").strip()
    focus_symbol = None
    session = memory_ctx["session"]
    if isinstance(session.focus_subject, dict):
        focus_symbol = session.focus_subject.get("symbol") or getattr(session, "last_focus_symbol", None)
    symbol_match = _SYMBOL_RE.findall(msg)
    rank = _parse_rank(msg)
    freshness = "next_session_plan" if _contains_any(msg, _POSTCLOSE_WORDS) else "latest_5m" if _contains_any(msg, _LIVE_WORDS) else "active_run"

    if _contains_any(msg, _CHAT_WORDS):
        return _fallback_frame(msg, subject="market", request="chat", freshness="active_run", confidence=0.95, note="chat fallback")
    if _contains_any(msg, _TERM_EXPLAIN_WORDS):
        refs = {}
        if symbol_match:
            refs["symbol"] = symbol_match[0]
        elif focus_symbol:
            refs["symbol"] = focus_symbol
        return _fallback_frame(msg, subject=("symbol" if refs.get("symbol") else "market"), request="term_explain", freshness="active_run", references=refs, confidence=0.92, note="term explain fallback")
    if _contains_any(msg, _RUN_CHANGE_WORDS):
        return _fallback_frame(msg, subject="run", request="run_change", freshness="active_run", confidence=0.88, note="run change fallback")
    if _contains_any(msg, _COMPARE_WORDS):
        refs: Dict[str, Any] = {}
        if len(symbol_match) >= 2:
            refs["compare_symbols"] = symbol_match[:3]
        elif rank is not None:
            refs["rank"] = rank
        return _fallback_frame(msg, subject="compare_set", request="compare", freshness="active_run", references=refs, confidence=0.82, note="compare fallback")
    if _contains_any(msg, _EXIT_WORDS):
        refs = {"symbol": symbol_match[0]} if symbol_match else ({"symbol": focus_symbol} if focus_symbol else {})
        return _fallback_frame(msg, subject="holding", request="exit_decision", freshness="latest_5m", references=refs, confidence=0.86, note="exit fallback")
    if _contains_any(msg, _LIVE_WORDS):
        refs = {}
        if symbol_match:
            refs["symbol"] = symbol_match[0]
        elif rank is not None:
            refs["rank"] = rank
        elif focus_symbol:
            refs["symbol"] = focus_symbol
        request = "live_entry_check" if refs else "no_trade_explain"
        subject = "symbol" if refs else "market"
        return _fallback_frame(msg, subject=subject, request=request, freshness="latest_5m", references=refs, confidence=0.82, note="live fallback")
    if _contains_any(msg, _DETAIL_WORDS) or _contains_any(msg, _DECISION_BASIS_WORDS):
        refs = {}
        if symbol_match:
            refs["symbol"] = symbol_match[0]
        elif rank is not None:
            refs["rank"] = rank
        elif focus_symbol and ("这只" in msg or "这个" in msg):
            refs["symbol"] = focus_symbol
        request = "pick_detail" if refs else "no_trade_explain"
        subject = "symbol" if refs and refs.get("symbol") else ("pick" if refs.get("rank") else "market")
        return _fallback_frame(msg, subject=subject, request=request, freshness=freshness, references=refs, confidence=0.84, note="detail fallback")
    if _contains_any(msg, _NO_TRADE_WORDS):
        refs = {"symbol": focus_symbol} if focus_symbol and ("这只" in msg or "这个" in msg) else {}
        subject = "symbol" if refs.get("symbol") else "market"
        request = "live_entry_check" if subject == "symbol" else "no_trade_explain"
        return _fallback_frame(msg, subject=subject, request=request, freshness=freshness, references=refs, confidence=0.78, note="risk fallback")

    topk = _parse_topk(msg)
    if topk is not None or _contains_any(msg, ("机会", "推荐", "标的", "看看", "值得看", "榜单")):
        return _fallback_frame(
            msg,
            subject="run",
            request="recommend",
            freshness="rebuild_run" if _contains_any(msg, _REFRESH_WORDS) else freshness,
            constraints={"topk": topk or 3, "require_refresh": _contains_any(msg, _REFRESH_WORDS)},
            confidence=0.9,
            note="recommend fallback",
        )
    return _fallback_frame(msg, subject="market", request="chat", freshness="active_run", confidence=0.35, note="default fallback")


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
        frame.constraints["topk"] = _clamp_topk(int(frame.constraints.get("topk") or 3))
    if frame.request == "live_entry_check" and frame.freshness == "active_run":
        frame.freshness = "latest_5m"
    if (
        frame.request == "recommend"
        and frame.freshness == "active_run"
        and book is not None
        and str(book.market_phase or "").upper() in {"POSTCLOSE_PENDING", "POSTCLOSE_READY", "PREOPEN", "OPEN_NO_FIRST_BAR", "NON_TRADING"}
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
    confidence = float((frame.ambiguity or {}).get("confidence", 0.5))
    focus_symbol = refs.get("focus_symbol") or getattr(memory_ctx["session"], "last_focus_symbol", None)

    if frame.request in {"pick_detail", "live_entry_check", "exit_decision"}:
        if not any(refs.get(key) for key in ("symbol", "rank")) and focus_symbol:
            refs["symbol"] = focus_symbol
        if frame.request == "pick_detail" and not refs.get("symbol") and not refs.get("rank") and confidence < 0.55:
            frame.request = "chat"
            frame.subject = "market"
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
    fallback = _fallback_semantic_parse(memory_ctx, book, user_message)
    try:
        frame = parse_turn_frame(context, user_message)
    except Exception:
        frame = fallback
    notes = " ".join((frame.ambiguity or {}).get("notes") or []).lower()
    if frame.request == "chat" and ("llm unavailable" in notes or _parse_topk(user_message or "") is not None or fallback.request != "chat"):
        frame = fallback
    frame = normalize_turn_frame(frame, book=book)
    frame = inject_entity_hints(frame, memory_ctx, book)
    frame = _validate_intent(frame, memory_ctx)
    frame = normalize_turn_frame(frame, book=book)
    return validate_turn_frame(frame)


def quick_parse_concern(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    frame = _fallback_semantic_parse(memory_ctx, book, user_message)
    frame = normalize_turn_frame(frame, book=book)
    frame = inject_entity_hints(frame, memory_ctx, book)
    frame = _validate_intent(frame, memory_ctx)
    frame = normalize_turn_frame(frame, book=book)
    return validate_turn_frame(frame)
