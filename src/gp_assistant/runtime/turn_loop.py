from __future__ import annotations

import json
from typing import Any, Dict, List

from ..book.engine import load_current_book
from ..book.repo import load_run
from ..contracts.objects import (
    AgentToolResult,
    BoardEntry,
    DecisionBasis,
    EvidencePack,
    GroundingSummary,
    Judgment,
    MarketBook,
    ReplyBundle,
    TurnFrame,
)
from ..core.logging import logger
from ..judgment.chat import judge_chat
from ..judgment.engine import make_judgment
from ..llm.client import LLMClient
from ..memory.service import commit_turn, load_memory_context
from ..worker import reconcile_runtime_state
from .concern_parser import parse_concern, quick_parse_concern
from .dialogue_text import clean_user_reasons, execution_state_label, explain_observation_reasons, intraday_runtime_enabled
from .evidence_planner import plan_evidence
from .grounding import validate_reply
from .narrator import build_default_text, build_reply, build_structured_reply
from .reference_resolver import resolve_subject_and_compare
from .repair import RepairStatusSnapshot, load_repair_status_snapshot


def _run_has_stale_daily(run) -> bool:
    if run is None:
        return False
    for entry in list(getattr(run, "picks", []) or []):
        pick = getattr(entry, "pick", None)
        meta = dict(getattr(pick, "meta", {}) or {})
        state = str(meta.get("daily_freshness_state") or "").strip().lower()
        if state and state != "current":
            return True
    return False


def _slot_key(value: str | None) -> str:
    return str(value or "").strip()


def _book_effective_day(book: MarketBook) -> str:
    return str(book.daybook_effective_day or book.daybook.trading_day or "").strip()


def _book_covers_repair_target(book: MarketBook, snapshot: RepairStatusSnapshot | None) -> bool:
    if snapshot is None:
        return True
    target_day = str(snapshot.daily_target_day or "").strip()
    if target_day and _book_effective_day(book) != target_day:
        return False
    target_slot = _slot_key(snapshot.pulse_target_slot_at)
    if not target_slot:
        return True
    target_trade_day = str(snapshot.pulse_target_trade_day or "").strip()
    if target_trade_day and str(book.pulse_trade_day or "").strip() != target_trade_day:
        return False
    book_slot = _slot_key(book.pulse_slot_at)
    if not book_slot or book_slot < target_slot:
        return False
    slot_status = str(book.slot_status or "").strip().upper()
    return bool(slot_status) and slot_status != "UNAVAILABLE"


def _repair_blocks_market_answers(
    book: MarketBook,
    *,
    snapshot: RepairStatusSnapshot | None = None,
    blocking_reason_override: str | None = None,
) -> bool:
    if blocking_reason_override:
        return True
    snapshot = snapshot if snapshot is not None else load_repair_status_snapshot()
    if snapshot is None:
        return False
    status = str(snapshot.repair_status or "ready").strip().lower()
    if status == "blocked":
        return True
    if status not in {"running", "failed"}:
        return False
    return not _book_covers_repair_target(book, snapshot)


def _should_invalidate_active_run(session, book: MarketBook, active_run) -> bool:
    if active_run is None:
        return False
    if session.active_run_daybook_effective_day and session.active_run_daybook_effective_day != (
        book.daybook_effective_day or book.daybook.trading_day
    ):
        return True
    if session.active_run_pulse_trade_day and session.active_run_pulse_trade_day != book.pulse_trade_day:
        return True
    if session.active_run_pulse_slot_at and session.active_run_pulse_slot_at != book.pulse_slot_at:
        return True
    if active_run.book_version and active_run.book_version != book.book_version:
        return True
    if active_run.artifact_id and active_run.artifact_id != book.artifact_id:
        return True
    if _run_has_stale_daily(active_run):
        return True
    return False


def _resolve_subject_entry(frame: TurnFrame, memory_ctx: Dict[str, Any], book: MarketBook, active_run, previous_run=None):
    session = memory_ctx["session"]
    raw = (frame.raw_message or "").strip()
    history_requested = any(token in raw for token in ("上一次", "上一轮", "之前", "历史"))
    active_entries = list(previous_run.picks) if history_requested and previous_run is not None else (
        list(active_run.picks) if active_run else list(book.board)
    )
    return resolve_subject_and_compare(frame=frame, session=session, book=book, active_entries=active_entries)


def build_evidence_pack(
    frame: TurnFrame,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
    plan: Dict[str, Any],
    *,
    invalidate_active_run: bool = False,
) -> EvidencePack:
    from ..evidence.portfolio_service import load_portfolio_snapshot
    from ..evidence.validation_service import build_validation_slice

    session = memory_ctx["session"]
    active_run = None if invalidate_active_run else (load_run(session.active_run_id) if plan.get("need_active_run") else None)
    previous_run = load_run(session.previous_run_id) if plan.get("need_previous_run") else None
    subject_entry = None
    compare_entries: List[BoardEntry] = []
    if plan.get("need_subject_entry") or plan.get("need_compare_entries"):
        subject_entry, compare_entries = _resolve_subject_entry(frame, memory_ctx, book, active_run, previous_run)
    strategy_id = None
    if subject_entry is not None:
        strategy_id = subject_entry.pick.strategy_id
    elif active_run and active_run.picks:
        strategy_id = active_run.picks[0].pick.strategy_id
    return EvidencePack(
        frame=frame,
        session=memory_ctx["session"],
        book=book,
        active_run=active_run,
        previous_run=previous_run,
        subject_entry=subject_entry,
        compare_entries=compare_entries,
        portfolio_slice=(load_portfolio_snapshot() if plan.get("need_portfolio") else {}),
        validation_slice=(build_validation_slice(strategy_id) if (plan.get("need_validation") and strategy_id) else {}),
        side_results=book.side_results,
        evidence_refs=[book.book_version],
    )


def _legacy_turn(session_id: str, user_message: str, memory_ctx: Dict[str, Any], book: MarketBook) -> tuple[ReplyBundle, Judgment]:
    frame = parse_concern(memory_ctx, book, user_message)
    if frame.request == "term_explain":
        result = _term_explain_result(session_id=session_id, memory_ctx=memory_ctx, book=book, frame=frame)
        reply = _bundle_from_tool_result(session_id, result, text=result.reply_text)
        judgment = judge_chat()
        return reply, judgment
    plan = plan_evidence(frame)
    session = memory_ctx["session"]
    active_run = load_run(session.active_run_id) if plan.get("need_active_run") and session.active_run_id else None
    invalidate_active_run = _should_invalidate_active_run(session, book, active_run)
    evidence = build_evidence_pack(frame, memory_ctx, book, plan, invalidate_active_run=invalidate_active_run)
    judgment = make_judgment(session_id=session_id, frame=frame, evidence=evidence)
    reply = build_reply(
        session_id=session_id,
        frame=frame,
        evidence=evidence,
        judgment=judgment,
        recent_turns=memory_ctx.get("recent_turns") or [],
    )
    validate_reply(reply, judgment)
    return reply, judgment


def _wants_decision_basis(user_message: str) -> bool:
    text = str(user_message or "").strip()
    keywords = ("怎么得出的", "怎么得出来的", "怎么来的", "依据是什么", "为什么这么判断", "怎么判断的")
    return any(keyword in text for keyword in keywords)


def _is_market_request(frame: TurnFrame) -> bool:
    return frame.request not in {"chat", "term_explain"}


def _latest_assistant_message(memory_ctx: Dict[str, Any]) -> Dict[str, Any]:
    turns = list(memory_ctx.get("recent_turns") or [])
    for turn in reversed(turns):
        if getattr(turn, "role", None) != "assistant":
            continue
        meta = dict(getattr(turn, "meta", {}) or {})
        message = meta.get("message")
        if isinstance(message, dict):
            return {"turn": turn, "meta": meta, "message": message}
    return {}


def _recent_assistant_messages(memory_ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    turns = list(memory_ctx.get("recent_turns") or [])
    for turn in reversed(turns):
        if getattr(turn, "role", None) != "assistant":
            continue
        meta = dict(getattr(turn, "meta", {}) or {})
        message = meta.get("message")
        if isinstance(message, dict):
            out.append({"turn": turn, "meta": meta, "message": message})
    return out


def _message_search_blob(message: Dict[str, Any]) -> str:
    chunks: List[str] = []
    for key in ("narrative_text", "message_kind", "symbol", "term"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            chunks.append(value.strip())
    for section in ("pick", "live_check", "exit_decision", "compare", "run"):
        value = message.get(section)
        if not isinstance(value, dict):
            continue
        for nested_key in ("symbol", "thesis", "why_selected", "summary", "entry_text", "stop_text", "take_text", "next_action", "status_reason"):
            nested = value.get(nested_key)
            if isinstance(nested, str) and nested.strip():
                chunks.append(nested.strip())
        for nested_list_key in ("gate_reasons", "comparison_points", "no_trade_reasons", "recovery_conditions"):
            nested_list = value.get(nested_list_key)
            if isinstance(nested_list, list):
                chunks.extend(str(item).strip() for item in nested_list if str(item).strip())
    return "\n".join(chunks)


def _find_term_explain_source(memory_ctx: Dict[str, Any], term: str, raw_message: str) -> Dict[str, Any]:
    messages = _recent_assistant_messages(memory_ctx)
    if not messages:
        return {}
    if "观察" in term or "为什么仅观察" in raw_message or "为什么只观察" in raw_message:
        for candidate in messages:
            message = dict(candidate.get("message") or {})
            if message.get("message_kind") in {"live_entry_check", "recommend", "no_trade"}:
                blob = _message_search_blob(message)
                if "观察" in blob or "WATCH_ONLY" in blob:
                    return candidate
    if term:
        for candidate in messages:
            blob = _message_search_blob(dict(candidate.get("message") or {}))
            if term in blob:
                return candidate
    return messages[0]


def _extract_term_text(user_message: str) -> str:
    text = str(user_message or "").strip().strip("？?。！!")
    prefixes = ("什么是", "这句话什么意思", "什么意思")
    for prefix in prefixes:
        if text.startswith(prefix):
            term = text[len(prefix):].strip("：:，,。 ")
            if term:
                return term
    suffixes = ("是什么意思", "什么意思")
    for suffix in suffixes:
        if text.endswith(suffix):
            term = text[: -len(suffix)].strip("：:，,。 ")
            if term:
                return term
    return text


def _term_explain_result(
    *,
    session_id: str,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
    frame: TurnFrame,
) -> AgentToolResult:
    latest = _find_term_explain_source(memory_ctx, _extract_term_text(frame.raw_message), frame.raw_message)
    if not latest:
        latest = _latest_assistant_message(memory_ctx)
    message = dict(latest.get("message") or {})
    meta = dict(latest.get("meta") or {})
    term = _extract_term_text(frame.raw_message)
    reply_text = "我先按上一轮已经给出的结论继续解释。"
    suggestions = ["这只现在还能买吗", "为什么仅观察", "今天给我 3 只"]

    if "观察" in term or "为什么仅观察" in frame.raw_message or "为什么只观察" in frame.raw_message:
        live_check = dict(message.get("live_check") or {})
        run = dict(message.get("run") or {})
        gate_reasons = list(live_check.get("gate_reasons") or run.get("gate", {}).get("reasons") or [])
        state = str(live_check.get("execution_state") or "").strip() or "WATCH_ONLY"
        next_action = str(live_check.get("next_action") or "").strip() or "先等更清晰的入场确认。"
        reasons_text = explain_observation_reasons(gate_reasons)
        reply_text = (
            f"这里说“仅观察”，意思是现在先不建议主动追进去，不是这只票已经彻底失效。\n"
            f"当前状态更接近“{execution_state_label(state)}”，{reasons_text}。\n"
            f"执行上先按“{next_action}”处理，等闸门放行、回踩确认或量能条件改善后再看。"
        )
        suggestions = ["这只现在还能买吗", "什么条件下才算能买", "今天给我 3 只"]
    elif term and ("支撑带" in term or "止损" in term or "跌破" in term):
        latest_pick = dict(message.get("pick") or {})
        latest_live = dict(message.get("live_check") or {})
        stop_text = str(latest_pick.get("stop_text") or latest_live.get("stop_text") or "收盘有效跌破支撑带").strip()
        entry_text = str(latest_pick.get("entry_text") or latest_live.get("entry_text") or "").strip()
        take_text = str(latest_pick.get("take_text") or latest_live.get("take_text") or "").strip()
        reply_text = (
            f"“{term}”是在解释风控边界，不是让你盘中看到一下跌破就立刻追着卖。\n"
            f"它的含义是：如果收盘后价格确认跌出原先的支撑区域，原来的买入逻辑就要视为失效。\n"
            f"执行上通常要把它和买入区 {entry_text or '当前计划区间'}、止盈位 {take_text or '既定目标位'} 一起看；一旦收盘确认跌破 {stop_text}，就不再按原计划继续持有或新开仓。"
        )
        suggestions = ["这只现在还能买吗", "它的止盈止损点再说一遍", "为什么仅观察"]
    else:
        narrative_text = str(message.get("narrative_text") or getattr(latest.get("turn"), "content", "") or "").strip()
        if narrative_text:
            reply_text = (
                f"你这句是在追问上一轮的表述。\n"
                f"上一轮的核心结论是：{narrative_text}\n"
                f"如果你要，我可以继续把它拆成“为什么这样判断、现在该怎么执行、什么条件下结论会变化”三部分。"
            )
            suggestions = ["为什么这样判断", "现在该怎么执行", "什么条件下结论会变化"]

    return AgentToolResult(
        tool_name="explain_followup",
        reply_text=reply_text,
        message={
            "message_kind": "term_explain",
            "narrative_text": reply_text,
            "term": term,
            "source_message_kind": message.get("message_kind") or meta.get("kind"),
            "followup_suggestions": suggestions,
            "freshness_meta": {
                "market_phase": book.market_phase,
                "daybook_effective_day": book.daybook_effective_day,
                "pulse_slot_at": book.pulse_slot_at,
            },
        },
        right_panel={
            "snapshot": None,
            "trading_day": book.trading_day,
            "artifact_id": book.artifact_id,
            "slot_id": book.slot_id,
            "slot_status": book.slot_status,
            "last_closed_5m": book.last_closed_5m,
            "tradeable": bool(book.daybook.tradeable),
            "run_action": None,
            "top3": [],
        },
        grounding_summary=GroundingSummary(
            market_phase=book.market_phase,
            daily_target_day=book.daybook_effective_day or book.daybook.trading_day,
            pulse_slot_at=book.pulse_slot_at,
            repair_status="ready",
            decision_basis_labels=["followup_explain", "session_context"],
        ),
    )


def _tool_schema(name: str, description: str) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }


def _assistant_context_result(book: MarketBook) -> AgentToolResult:
    intraday_enabled = intraday_runtime_enabled()
    reply_text = (
        "你好，我可以直接帮你看今天的候选、某只票还能不能买、止盈止损怎么设，或者解释上一条结论。"
        if intraday_enabled
        else "你好，我可以直接帮你看今天的候选、解释某只票为什么入选，或者说明当前该观察什么。盘中 5 分钟执行数据现在是停用的。"
    )
    summary = GroundingSummary(
        market_phase=book.market_phase,
        daily_target_day=book.daybook_effective_day or book.daybook.trading_day,
        pulse_slot_at=book.pulse_slot_at,
        repair_status="ready",
        decision_basis_labels=["product_context", "risk_boundary"],
    )
    return AgentToolResult(
        tool_name="get_assistant_context",
        reply_text=reply_text,
        message={
            "message_kind": "chat",
            "narrative_text": reply_text,
            "followup_suggestions": ["给我当前推荐的前三个标的", "这只票为什么能上榜", "今天适合空仓观察还是执行计划"],
            "freshness_meta": {
                "market_phase": book.market_phase,
                "daybook_effective_day": book.daybook_effective_day,
                "pulse_slot_at": book.pulse_slot_at,
            },
        },
        grounding_summary=summary,
    )


def _market_ready_result(
    book: MarketBook,
    *,
    snapshot: RepairStatusSnapshot | None = None,
    blocking_reason_override: str | None = None,
) -> AgentToolResult:
    snapshot = snapshot if snapshot is not None else load_repair_status_snapshot()
    repair_status = str(snapshot.repair_status if snapshot else "ready")
    market_blocked = _repair_blocks_market_answers(
        book,
        snapshot=snapshot,
        blocking_reason_override=blocking_reason_override,
    )
    blocking_reason = None
    if blocking_reason_override:
        if repair_status not in {"running", "blocked", "failed"}:
            repair_status = "running"
        blocking_reason = blocking_reason_override
    elif market_blocked and snapshot is not None and repair_status in {"running", "blocked", "failed"}:
        blocking_reason = snapshot.blocking_reason or "运行时数据仍在修复中，暂时不能发布正式市场结论。"
    market_phase = (
        getattr(snapshot, "market_phase", None) or book.market_phase
        if snapshot is not None and repair_status in {"running", "blocked", "failed"}
        else book.market_phase
    )
    summary = GroundingSummary(
        market_phase=market_phase,
        daily_target_day=(snapshot.daily_target_day if snapshot else (book.daybook_effective_day or book.daybook.trading_day)),
        pulse_slot_at=(snapshot.pulse_target_slot_at if snapshot else book.pulse_slot_at),
        repair_status=repair_status,
        decision_basis_labels=["修复状态", "运行时状态"],
    )
    if market_blocked and blocking_reason:
        message = {
            "message_kind": "chat",
            "narrative_text": "当前运行时数据还在修复中，暂不发布正式市场结论。你可以先等待 worker 完成修复，或者稍后再问我最新推荐。",
            "followup_suggestions": ["刷新当前修复状态", "修复完成后再给我最新推荐"],
            "freshness_meta": {
                "market_phase": market_phase,
                "daybook_effective_day": book.daybook_effective_day,
                "pulse_slot_at": book.pulse_slot_at,
            },
        }
        return AgentToolResult(
            tool_name="ensure_market_ready",
            reply_text=message["narrative_text"],
            message=message,
            right_panel={
                "snapshot": None,
                "trading_day": book.trading_day,
                "artifact_id": book.artifact_id,
                "slot_id": book.slot_id,
                "slot_status": book.slot_status,
                "last_closed_5m": book.last_closed_5m,
                "tradeable": False,
                "run_action": "NO_TRADE",
                "top3": [],
            },
            grounding_summary=summary,
            decision_basis={
                "labels": ["修复中"],
                "market_phase": market_phase,
                "daily_target_day": summary.daily_target_day,
                "pulse_slot_at": summary.pulse_slot_at,
                "selection_reason": blocking_reason,
                "execution_reason": None,
                "risk_notes": [],
                "repair_status": repair_status,
                "repair_stage": snapshot.repair_stage if snapshot else None,
            },
        )
    return AgentToolResult(
        tool_name="ensure_market_ready",
        reply_text="当前运行时数据已经达到可回答状态，可以继续基于最新快照给出推荐、解释和比较结论。",
        message={
            "message_kind": "chat",
            "narrative_text": "当前运行时数据已经达到可回答状态，可以继续基于最新快照给出推荐、解释和比较结论。",
            "followup_suggestions": [],
            "freshness_meta": {
                "market_phase": book.market_phase,
                "daybook_effective_day": book.daybook_effective_day,
                "pulse_slot_at": book.pulse_slot_at,
            },
        },
        grounding_summary=summary,
    )


def _override_frame(frame: TurnFrame, *, request: str | None = None) -> TurnFrame:
    clone = frame.model_copy(deep=True)
    if request is not None:
        clone.request = request
    return clone


def _explanation_frame(frame: TurnFrame, memory_ctx: Dict[str, Any]) -> TurnFrame:
    session = memory_ctx["session"]
    if frame.request in {
        "pick_detail",
        "live_entry_check",
        "compare",
        "exit_decision",
        "no_trade_explain",
    }:
        return frame
    clone = frame.model_copy(deep=True)
    if frame.request == "recommend":
        clone.subject = "run"
        clone.request = "recommend"
        return clone
    if getattr(session, "last_focus_symbol", None):
        clone.subject = "symbol"
        clone.request = "pick_detail"
        clone.references["symbol"] = session.last_focus_symbol
        return clone
    if session.active_run_id:
        clone.subject = "run"
        clone.request = "recommend"
        return clone
    clone.subject = "market"
    clone.request = "no_trade_explain"
    return clone


def _business_tool(
    *,
    tool_name: str,
    session_id: str,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
    frame: TurnFrame,
) -> tuple[AgentToolResult, Judgment]:
    request_map = {
        "explain_followup": "term_explain",
        "get_recommendation": "recommend",
        "get_pick_detail": "pick_detail",
        "get_live_entry_check": "live_entry_check",
        "compare_symbols": "compare",
        "get_exit_decision": "exit_decision",
        "get_run_change": "run_change",
    }
    if tool_name == "explain_followup":
        return _term_explain_result(session_id=session_id, memory_ctx=memory_ctx, book=book, frame=frame), judge_chat()
    tool_frame = _override_frame(frame, request=request_map.get(tool_name))
    if tool_name == "explain_decision_basis":
        tool_frame = _explanation_frame(frame, memory_ctx)
    plan = plan_evidence(tool_frame)
    session = memory_ctx["session"]
    active_run = load_run(session.active_run_id) if plan.get("need_active_run") and session.active_run_id else None
    invalidate_active_run = _should_invalidate_active_run(session, book, active_run)
    evidence = build_evidence_pack(tool_frame, memory_ctx, book, plan, invalidate_active_run=invalidate_active_run)
    judgment = make_judgment(session_id=session_id, frame=tool_frame, evidence=evidence)
    provisional_text = build_default_text(judgment)
    reply = build_structured_reply(session_id, evidence, judgment, text=provisional_text)
    if tool_name == "explain_decision_basis":
        reply_text = _explain_decision_text(reply, judgment)
        reply = reply.model_copy(
            update={
                "text": reply_text,
                "message": {
                    **dict(reply.message or {}),
                    "narrative_text": reply_text,
                },
            }
        )
    result = AgentToolResult(
        tool_name=tool_name,
        reply_text=reply.text,
        message=reply.message,
        right_panel=reply.right_panel,
        ui_items=reply.ui_items,
        run_id=reply.run_id,
        symbols=reply.symbols,
        grounding_summary=GroundingSummary.model_validate(reply.grounding_summary),
        decision_basis=reply.decision_basis,
        tool_trace={"request": tool_frame.request},
    )
    return result, judgment


def _market_phase_label(value: str | None) -> str:
    mapping = {
        "PREOPEN": "盘前准备阶段",
        "OPEN_NO_FIRST_BAR": "开盘初期",
        "INTRADAY_AM": "上午盘中",
        "LUNCH_BREAK": "午间休市",
        "INTRADAY_PM": "下午盘中",
        "CLOSING_AUCTION": "收盘集合竞价阶段",
        "POSTCLOSE_PENDING": "收盘后待确认阶段",
        "POSTCLOSE_READY": "盘后准备阶段",
        "NON_TRADING": "非交易时段",
    }
    key = str(value or "").strip().upper()
    return mapping.get(key, "当前市场阶段")


def _execution_state_label(value: str | None) -> str | None:
    label = execution_state_label(value)
    return label if label != "继续观察" else None


def _safe_risk_notes(notes: list[str] | None) -> list[str]:
    return clean_user_reasons(notes or [])


def _explain_decision_text(reply: ReplyBundle, judgment: Judgment) -> str:
    basis = DecisionBasis.model_validate(reply.decision_basis or {})
    parts: list[str] = []
    market_phase = _market_phase_label(basis.market_phase)
    daily_target_day = basis.daily_target_day or "当前交易日"
    if intraday_runtime_enabled():
        pulse_slot_at = basis.pulse_slot_at or "最新可读快照"
        parts.append(f"这个结论是基于当前{market_phase}的快照得出的，日线使用的是 {daily_target_day}，盘中参考到 {pulse_slot_at}。")
    else:
        parts.append(f"这个结论是基于当前{market_phase}的快照得出的，当前只使用日线计划和观察结论，生效日是 {daily_target_day}。")

    detail = judgment.pick_detail
    if detail is not None:
        subject = detail.symbol + (f" {detail.name}" if detail.name else "")
        selection_reason = detail.why_selected or detail.thesis or basis.selection_reason
        if selection_reason:
            parts.append(f"{subject} 的核心依据是：{selection_reason}。")
        execution_bits: list[str] = []
        if detail.entry_text:
            execution_bits.append(f"参考买入区间 {detail.entry_text}")
        if detail.stop_text or detail.invalidation:
            execution_bits.append(f"风控看 {detail.stop_text or detail.invalidation}")
        if detail.take_text:
            execution_bits.append(f"止盈参考 {detail.take_text}")
        if execution_bits:
            parts.append("执行上，" + "，".join(execution_bits) + "。")
        state_text = _execution_state_label(detail.execution_state)
        if state_text:
            parts.append(f"当前执行状态是{state_text}。")
    elif judgment.canonical_run is not None:
        run = judgment.canonical_run
        if basis.selection_reason:
            parts.append(f"这轮计划的核心依据是：{basis.selection_reason}。")
        if run.status_reason:
            parts.append(f"当前结论是：{run.status_reason}")
        if run.picks:
            top = run.picks[0]
            subject = top.symbol + (f" {top.name}" if top.name else "")
            parts.append(f"当前排在前面的标的是 {subject}，主要因为它相对同组候选更贴近计划买点，且执行条件更完整。")
        if basis.execution_reason:
            parts.append(f"执行上主要参考：{basis.execution_reason}。")

    risk_notes = _safe_risk_notes(basis.risk_notes)
    if risk_notes:
        parts.append("风险前提：" + "；".join(risk_notes[:3]) + "。")
    if basis.repair_status != "ready":
        parts.append("后台数据仍在滚动刷新，但当前快照已经达到可解释状态。")
    return "\n".join(parts)


def _agent_system_prompt() -> str:
    return (
        "你是一个 A 股短线股票助手。"
        "你必须先读取工具结果，再用正常业务语言回答用户。"
        "不要提到代码、模块名、planner trace、tool 名称、内部实现或调试字段。"
        "如果工具显示数据仍在修复中，就明确说明数据修复中，暂不发布正式结论。"
        "如果工具给出推荐、单票、比较、卖出或变更结果，只能基于这些结果作答，不要编造。"
    )


def _extract_llm_text(response: Dict[str, Any]) -> str:
    try:
        return str(((response or {}).get("choices") or [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""


def _tool_call_name(tool_call: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    return str(function.get("name") or "").strip()


def _append_tool_messages(messages: List[Dict[str, Any]], assistant_step: Dict[str, Any], result: AgentToolResult) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": assistant_step.get("content"),
            "tool_calls": assistant_step.get("tool_calls") or [],
        }
    )
    tool_call = (assistant_step.get("tool_calls") or [{}])[0]
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.get("id") or result.tool_name,
            "name": result.tool_name,
            "content": json.dumps(result.model_dump(), ensure_ascii=False),
        }
    )


def _execute_single_tool_round(
    client: LLMClient,
    messages: List[Dict[str, Any]],
    *,
    schema: Dict[str, Any],
    fallback_result: AgentToolResult,
) -> AgentToolResult:
    step = client.run_chat_with_tools(messages, tools=[schema], temperature=0.0)
    tool_calls = step.get("tool_calls") or []
    if not tool_calls:
        step = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": fallback_result.tool_name, "type": "function", "function": {"name": fallback_result.tool_name, "arguments": "{}"}}],
        }
    elif _tool_call_name(tool_calls[0]) != fallback_result.tool_name:
        step = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": fallback_result.tool_name, "type": "function", "function": {"name": fallback_result.tool_name, "arguments": "{}"}}],
        }
    _append_tool_messages(messages, step, fallback_result)
    return fallback_result


def _final_text_from_tools(
    client: LLMClient,
    messages: List[Dict[str, Any]],
    *,
    fallback_text: str,
) -> str:
    response = client.chat(
        [
            *messages,
            {
                "role": "system",
                "content": "现在只根据上面的工具结果给出最终答复。使用自然业务语言，简洁表达，避免泄露内部实现。",
            },
        ],
        temperature=0.2,
    )
    text = _extract_llm_text(response)
    return text or fallback_text


def _bundle_from_tool_result(session_id: str, result: AgentToolResult, *, text: str) -> ReplyBundle:
    message = dict(result.message or {})
    if message:
        message["narrative_text"] = text
    return ReplyBundle(
        session_id=session_id,
        text=text,
        kind=str(message.get("message_kind") or "chat"),
        run_id=result.run_id,
        symbols=list(result.symbols or []),
        right_panel=dict(result.right_panel or {}),
        ui_items=list(result.ui_items or []),
        message=message,
        grounding_summary=result.grounding_summary.model_dump(),
        decision_basis=result.decision_basis.model_dump(),
        tool_trace={"tool_name": result.tool_name},
    )


def _reconcile_before_turn(*, operation: str = "auto") -> str | None:
    try:
        reconcile_runtime_state(operation=operation, lock_timeout_sec=0.0)
    except TimeoutError as ex:
        logger.warning("[turn] runtime reconcile busy, continue with current snapshot: %s", ex)
        return str(ex)
    return None


def run_turn_sync(session_id: str | None, user_message: str) -> Dict[str, Any]:
    session_id = session_id or "default"
    memory_ctx = load_memory_context(session_id)
    book = load_current_book()
    repair_blocking_reason = None
    if book is None:
        repair_blocking_reason = _reconcile_before_turn(operation="auto")
        book = load_current_book()
    if book is None:
        raise RuntimeError("current book unavailable")
    try:
        logger.info(
            "[turn] load session=%s request=%s book=%s day=%s pulse_day=%s slot=%s phase=%s status=%s",
            session_id,
            (user_message[:60] if isinstance(user_message, str) else str(user_message)),
            book.book_version,
            book.daybook_effective_day or book.daybook.trading_day,
            book.pulse_trade_day,
            book.pulse_slot_at,
            book.market_phase,
            book.data_status,
        )
    except Exception:
        pass

    quick_frame = quick_parse_concern(memory_ctx, book, user_message)
    market_request = _is_market_request(quick_frame) or _wants_decision_basis(user_message)
    if market_request:
        snapshot = load_repair_status_snapshot()
        market_ready = _market_ready_result(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason)
        if _repair_blocks_market_answers(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason):
            judgment = judge_chat()
            reply = _bundle_from_tool_result(session_id, market_ready, text=market_ready.reply_text)
            validate_reply(reply, judgment)
            commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
            return {
                "session_id": reply.session_id,
                "reply": reply.text,
                "message": reply.message,
                "run_id": reply.run_id,
                "symbols": reply.symbols,
                "right_panel": reply.right_panel,
                "ui_items": reply.ui_items,
                "grounding_summary": reply.grounding_summary,
            }

    frame = parse_concern(memory_ctx, book, user_message)
    market_request = _is_market_request(frame) or _wants_decision_basis(user_message)

    client = LLMClient()
    try:
        ok, _ = client.available()
    except Exception:
        ok = False

    if not ok:
        reply, judgment = _legacy_turn(session_id, user_message, memory_ctx, book)
        commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
        return {
            "session_id": reply.session_id,
            "reply": reply.text,
            "message": reply.message,
            "run_id": reply.run_id,
            "symbols": reply.symbols,
            "right_panel": reply.right_panel,
            "ui_items": reply.ui_items,
            "grounding_summary": reply.grounding_summary,
        }

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _agent_system_prompt()},
        {"role": "user", "content": user_message},
    ]
    try:
        assistant_context = _assistant_context_result(book)
        _execute_single_tool_round(
            client,
            messages,
            schema=_tool_schema(
                "get_assistant_context",
                "Load the assistant background, market coverage, and user-safe explanation boundaries.",
            ),
            fallback_result=assistant_context,
        )

        active_result = assistant_context
        active_judgment = judge_chat()
        if frame.request == "term_explain":
            active_result, active_judgment = _business_tool(
                tool_name="explain_followup",
                session_id=session_id,
                memory_ctx=memory_ctx,
                book=book,
                frame=frame,
            )
            active_result = _execute_single_tool_round(
                client,
                messages,
                schema=_tool_schema(
                    "explain_followup",
                    "Explain the most recent assistant wording or term using the already committed session conclusion, without recomputing a new market judgment.",
                ),
                fallback_result=active_result,
            )
        elif market_request:
            snapshot = load_repair_status_snapshot()
            market_ready = _market_ready_result(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason)
            active_result = _execute_single_tool_round(
                client,
                messages,
                schema=_tool_schema(
                    "ensure_market_ready",
                    "Check whether the current market-facing answer can be published or whether runtime repair is still in progress.",
                ),
                fallback_result=market_ready,
            )
            if not _repair_blocks_market_answers(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason):
                wants_basis = _wants_decision_basis(user_message)
                if frame.request == "term_explain":
                    tool_name = "explain_followup"
                    description = "Explain the most recent assistant wording or term using the already committed session conclusion, without recomputing a new market judgment."
                elif wants_basis:
                    tool_name = "explain_decision_basis"
                    description = "Explain how the current conclusion was derived using market phase, daybook day, 5-minute slot, selection basis, execution state, and risk boundaries."
                else:
                    tool_name = {
                        "recommend": "get_recommendation",
                        "pick_detail": "get_pick_detail",
                        "live_entry_check": "get_live_entry_check",
                        "compare": "compare_symbols",
                        "exit_decision": "get_exit_decision",
                        "run_change": "get_run_change",
                        "no_trade_explain": "explain_decision_basis",
                    }.get(frame.request, "get_recommendation")
                    description = {
                        "get_recommendation": "Return the current short-term stock recommendation set for the active market phase.",
                        "get_pick_detail": "Return the detail, rationale, and plan for the current subject stock.",
                        "get_live_entry_check": "Return whether the current subject stock can be executed now and what to do next.",
                        "compare_symbols": "Compare the current candidate symbols and explain which one is stronger.",
                        "get_exit_decision": "Return the current exit or hold decision for the subject stock.",
                        "get_run_change": "Explain how the current recommendation run changed versus the previous one.",
                        "explain_decision_basis": "Explain how the current conclusion was derived using market phase, daybook day, 5-minute slot, selection basis, execution state, and risk boundaries.",
                    }[tool_name]
                business_result, active_judgment = _business_tool(
                    tool_name=tool_name,
                    session_id=session_id,
                    memory_ctx=memory_ctx,
                    book=book,
                    frame=frame,
                )
                active_result = _execute_single_tool_round(
                    client,
                    messages,
                    schema=_tool_schema(tool_name, description),
                    fallback_result=business_result,
                )
        final_text = active_result.reply_text or _final_text_from_tools(client, messages, fallback_text=user_message)
        reply = _bundle_from_tool_result(session_id, active_result, text=final_text)
        validate_reply(reply, active_judgment)
        commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=active_judgment)
        return {
            "session_id": reply.session_id,
            "reply": reply.text,
            "message": reply.message,
            "run_id": reply.run_id,
            "symbols": reply.symbols,
            "right_panel": reply.right_panel,
            "ui_items": reply.ui_items,
            "grounding_summary": reply.grounding_summary,
        }
    except Exception as ex:
        logger.exception("[turn] tool agent failed, fallback to legacy path: %s", ex)
        reply, judgment = _legacy_turn(session_id, user_message, memory_ctx, book)
        commit_turn(session_id=session_id, user_message=user_message, reply=reply, judgment=judgment)
        return {
            "session_id": reply.session_id,
            "reply": reply.text,
            "message": reply.message,
            "run_id": reply.run_id,
            "symbols": reply.symbols,
            "right_panel": reply.right_panel,
            "ui_items": reply.ui_items,
            "grounding_summary": reply.grounding_summary,
        }


run_turn = run_turn_sync
