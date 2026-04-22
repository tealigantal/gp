from __future__ import annotations

import re
from typing import Any, Dict

from .context_engine import build_context
from ..contracts.objects import MarketBook, TurnFrame
from ..llm.interpret import parse_turn_frame
from ..runtime.utils import gen_id

_SYMBOL_RE = re.compile(r"(?<!\d)(?:60|00|30)\d{4}(?!\d)")
_STRATEGY_ID_RE = re.compile(r"\bs\s*\d{1,2}\b", re.IGNORECASE)
_TOPK_RE = re.compile(r"(?:推荐|来|给|选|挑).{0,8}?(\d{1,2})\s*只")
_ARABIC_RANK_RE = re.compile(r"第\s*(\d{1,2})\s*(?:只|个|名)?")

_COMMON_CHAT_PREFIXES = (
    "你好",
    "您好",
    "嗨",
    "hello",
    "hi",
    "hey",
    "谢谢",
    "多谢",
)
_CHAT_HELP_KEYWORDS = ("你是谁", "你能做什么", "帮助", "help", "怎么用")
_STRATEGY_ASK_KEYWORDS = ("策略", "是什么", "哪些", "介绍", "解释", "区别", "含义")
_RUN_ANCHOR_KEYWORDS = ("当前", "目前", "这些", "本轮", "上轮", "推荐", "第一只", "第二只", "第三只")
_LIVE_CHECK_KEYWORDS = ("还能买吗", "现在能买吗", "盘中", "实时", "live", "状态")
_EXIT_KEYWORDS = ("卖", "卖出", "止损", "止盈", "离场", "退出")
_EXPLAIN_KEYWORDS = ("为什么", "逻辑", "原因", "怎么看", "什么时候买", "什么时候卖", "买比较好", "卖比较好")
_COMPARE_KEYWORDS = ("比较", "对比", "区别")


def _contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    lowered = text.lower()
    return any(k.lower() in lowered for k in keywords)


def _extract_rank_from_text(text: str) -> int | None:
    zh_map = {
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
    for token, rank in zh_map.items():
        if token in text:
            return rank
    match = _ARABIC_RANK_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _chat_frame(user_message: str, note: str) -> TurnFrame:
    return TurnFrame.model_validate(
        {
            "frame_id": gen_id("frame"),
            "raw_message": user_message,
            "subject": "market",
            "request": "chat",
            "freshness": "current_book",
            "references": {},
            "constraints": {},
            "ambiguity": {"confidence": 0.9, "notes": [note]},
        }
    )


def _is_general_chat_message(user_message: str) -> bool:
    msg = (user_message or "").strip()
    if not msg:
        return False
    lowered = msg.lower()
    if any(lowered.startswith(prefix) for prefix in _COMMON_CHAT_PREFIXES):
        return True
    if _contains_any(msg, _CHAT_HELP_KEYWORDS):
        return True
    if _STRATEGY_ID_RE.search(msg) and _contains_any(msg, _STRATEGY_ASK_KEYWORDS):
        return True
    if "s1-s14" in lowered and _contains_any(msg, _STRATEGY_ASK_KEYWORDS):
        return True
    return False


def _inject_reference_hints(frame: TurnFrame, memory_ctx: Dict[str, Any]) -> TurnFrame:
    refs = dict(frame.references or {})
    raw = (frame.raw_message or "").strip()
    session = memory_ctx["session"]

    if any(token in raw for token in ("这只", "它", "这个标的", "这个票")):
        focus = session.focus_subject if isinstance(session.focus_subject, dict) else {}
        if not refs.get("symbol") and focus.get("type") == "symbol":
            symbol = focus.get("symbol")
            if isinstance(symbol, str) and symbol:
                refs["symbol"] = symbol

    if refs.get("rank") is None:
        rank = _extract_rank_from_text(raw)
        if rank is not None:
            refs["rank"] = rank

    frame.references = refs
    return frame


def _quick_rule_parse(memory_ctx: Dict[str, Any], user_message: str) -> TurnFrame | None:
    msg = (user_message or "").strip()
    if not msg:
        return None

    if _is_general_chat_message(msg):
        return _chat_frame(msg, "generic chat or strategy catalog request")

    topk_match = _TOPK_RE.search(msg)
    if topk_match:
        try:
            topk = max(1, min(int(topk_match.group(1)), 10))
        except Exception:
            topk = 3
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "run",
                "request": "recommend",
                "freshness": "current_book",
                "references": {},
                "constraints": {"topk": topk},
                "ambiguity": {"confidence": 0.96, "notes": ["explicit recommendation count"]},
            }
        )

    if _contains_any(msg, ("今日推荐", "今天推荐", "推荐什么", "来点推荐")):
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "run",
                "request": "recommend",
                "freshness": "current_book",
                "references": {},
                "constraints": {"topk": 3},
                "ambiguity": {"confidence": 0.94, "notes": ["explicit recommendation request"]},
            }
        )

    symbol_match = _SYMBOL_RE.search(msg)
    if symbol_match and _contains_any(msg, _EXIT_KEYWORDS):
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "holding",
                "request": "exit",
                "freshness": "latest_5m",
                "references": {"symbol": symbol_match.group(0)},
                "constraints": {},
                "ambiguity": {"confidence": 0.92, "notes": ["explicit exit request with symbol"]},
            }
        )

    if _contains_any(msg, _LIVE_CHECK_KEYWORDS):
        refs: Dict[str, Any] = {}
        if symbol_match:
            refs["symbol"] = symbol_match.group(0)
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "symbol",
                "request": "live_check",
                "freshness": "latest_5m",
                "references": refs,
                "constraints": {},
                "ambiguity": {"confidence": 0.84, "notes": ["live check style query"]},
            }
        )

    if _contains_any(msg, _COMPARE_KEYWORDS):
        refs = {}
        symbols = _SYMBOL_RE.findall(msg)
        if len(symbols) >= 2:
            refs["compare_symbols"] = symbols[:3]
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "compare_set",
                "request": "compare",
                "freshness": "current_book",
                "references": refs,
                "constraints": {},
                "ambiguity": {"confidence": 0.82, "notes": ["comparison query"]},
            }
        )

    if _extract_rank_from_text(msg) is not None and _contains_any(msg, _EXPLAIN_KEYWORDS):
        return TurnFrame.model_validate(
            {
                "frame_id": gen_id("frame"),
                "raw_message": user_message,
                "subject": "pick",
                "request": "explain",
                "freshness": "current_book",
                "references": {"rank": _extract_rank_from_text(msg)},
                "constraints": {},
                "ambiguity": {"confidence": 0.86, "notes": ["rank-based explain query"]},
            }
        )

    return None


def _has_resolvable_target(frame: TurnFrame, memory_ctx: Dict[str, Any]) -> bool:
    refs = frame.references or {}
    if any(refs.get(key) for key in ("symbol", "symbols", "compare_symbols", "rank")):
        return True
    if _SYMBOL_RE.search(frame.raw_message or ""):
        return True
    session = memory_ctx["session"]
    if frame.request == "explain" and frame.subject == "run" and session.active_run_id:
        if _contains_any(frame.raw_message or "", _RUN_ANCHOR_KEYWORDS + _EXPLAIN_KEYWORDS):
            return True
    return False


def _coerce_ambiguous_tool_request(frame: TurnFrame, memory_ctx: Dict[str, Any]) -> TurnFrame:
    if frame.request == "chat":
        return frame

    msg = (frame.raw_message or "").strip()
    if _is_general_chat_message(msg):
        return _chat_frame(msg, "coerced to chat because the message is informational or social")

    confidence = 0.5
    try:
        confidence = float((frame.ambiguity or {}).get("confidence", 0.5))
    except Exception:
        confidence = 0.5

    has_target = _has_resolvable_target(frame, memory_ctx)
    missing_target_requests = {"exit", "live_check", "compare"}
    if frame.request in missing_target_requests and not has_target:
        return _chat_frame(msg, f"missing parameters for {frame.request}")

    if frame.request in {"explain", "run_change"} and not has_target and confidence < 0.75:
        return _chat_frame(msg, f"ambiguous {frame.request} request without resolvable target")

    return frame


def parse_concern(memory_ctx: Dict[str, Any], book: MarketBook, user_message: str) -> TurnFrame:
    frame = _quick_rule_parse(memory_ctx, user_message)
    if frame is None:
        context = build_context(memory_ctx, book)
        frame = parse_turn_frame(context, user_message)
    frame = _inject_reference_hints(frame, memory_ctx)
    frame = _coerce_ambiguous_tool_request(frame, memory_ctx)
    frame = normalize_turn_frame(frame)
    return validate_turn_frame(frame)


def normalize_turn_frame(frame: TurnFrame) -> TurnFrame:
    frame.references = frame.references or {}
    frame.constraints = frame.constraints or {}
    ambiguity = frame.ambiguity or {}
    try:
        confidence = float(ambiguity.get("confidence", 0.5))
        ambiguity["confidence"] = max(0.0, min(1.0, confidence))
    except Exception:
        ambiguity["confidence"] = 0.5
    notes = ambiguity.get("notes")
    ambiguity["notes"] = [str(item) for item in notes] if isinstance(notes, list) else []
    frame.ambiguity = ambiguity
    return frame


def validate_turn_frame(frame: TurnFrame) -> TurnFrame:
    allowed_requests = {"chat", "recommend", "explain", "live_check", "compare", "exit", "run_change"}
    allowed_subjects = {"run", "pick", "symbol", "compare_set", "holding", "market"}
    allowed_freshness = {"current_book", "latest_5m", "rebuild_daybook"}

    if frame.request not in allowed_requests:
        raise ValueError(f"Illegal request: {frame.request}")
    if frame.subject not in allowed_subjects:
        raise ValueError(f"Illegal subject: {frame.subject}")
    if frame.freshness not in allowed_freshness:
        raise ValueError(f"Illegal freshness: {frame.freshness}")
    return frame
