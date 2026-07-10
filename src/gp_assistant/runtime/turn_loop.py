from __future__ import annotations

import json
from typing import Any, Dict, List

from ..book.engine import load_current_book
from ..book.repo import load_run
from ..contracts.objects import (
    AgentActionTrace,
    AgentToolResult,
    BoardEntry,
    EvidencePack,
    GroundingSummary,
    Judgment,
    MarketBook,
    ReplyBundle,
    TurnFrame,
)
from ..core.errors import IntentLLMUnavailable
from ..core.config import load_config
from ..core.logging import logger
from ..judgment.chat import judge_chat
from ..judgment.engine import make_judgment
from ..llm.client import LLMClient
from ..memory.service import commit_turn, load_memory_context
from ..worker import reconcile_runtime_state
from .dialogue_text import execution_state_label, intraday_runtime_enabled
from .context_budget import ROUTING_PAYLOAD_LIMIT_BYTES, serialized_size_bytes
from .context_engine import (
    build_agent_routing_context,
    compact_agent_routing_context,
)
from .concern_parser import normalize_turn_frame
from .evidence_planner import plan_evidence
from .grounding import validate_reply
from .narrator import build_reply
from .reference_resolver import inject_entity_hints, resolve_subject_and_compare
from .repair import RepairStatusSnapshot, load_repair_status_snapshot
from .utils import gen_id


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
    constraints = dict(frame.constraints or {})
    history_requested = bool(constraints.get("history_mode")) or frame.request == "run_change"
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


def _is_market_request(frame: TurnFrame) -> bool:
    return frame.request not in {"chat", "term_explain"}


def _requires_runtime_market_ready(frame: TurnFrame) -> bool:
    return frame.request not in {"chat", "term_explain", "single_stock_query"}


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


_BUSINESS_MESSAGE_KINDS = {
    "pick_detail",
    "recommend",
    "single_stock_query",
    "live_entry_check",
    "exit_decision",
    "compare",
    "run_change",
    "no_trade",
}

def _message_kind(candidate: Dict[str, Any]) -> str:
    message = dict(candidate.get("message") or {})
    meta = dict(candidate.get("meta") or {})
    return str(message.get("message_kind") or meta.get("kind") or "").strip()


def _message_symbols(message: Dict[str, Any]) -> set[str]:
    symbols: set[str] = set()
    for value in (message.get("symbol"),):
        if isinstance(value, str) and value.strip():
            symbols.add(value.strip())
    for key in ("symbols",):
        values = message.get(key)
        if isinstance(values, list):
            symbols.update(str(item).strip() for item in values if str(item).strip())
    for key in ("pick", "live_check", "exit_decision"):
        value = message.get(key)
        if isinstance(value, dict) and str(value.get("symbol") or "").strip():
            symbols.add(str(value.get("symbol")).strip())
    for key in ("picks",):
        values = message.get(key)
        if isinstance(values, list):
            for item in values:
                if isinstance(item, dict) and str(item.get("symbol") or "").strip():
                    symbols.add(str(item.get("symbol")).strip())
    run = message.get("run")
    if isinstance(run, dict):
        for item in run.get("picks") or []:
            if isinstance(item, dict) and str(item.get("symbol") or "").strip():
                symbols.add(str(item.get("symbol")).strip())
    return symbols


def _find_term_explain_source(memory_ctx: Dict[str, Any], frame: TurnFrame) -> Dict[str, Any]:
    messages = _recent_assistant_messages(memory_ctx)
    if not messages:
        return {}
    refs = frame.references or {}
    wanted_symbol = str(refs.get("symbol") or refs.get("focus_symbol") or "").strip()
    session_symbol = str(getattr(memory_ctx["session"], "last_focus_symbol", None) or "").strip()
    for symbol in (wanted_symbol, session_symbol):
        if not symbol:
            continue
        for candidate in messages:
            message = dict(candidate.get("message") or {})
            if _message_kind(candidate) in _BUSINESS_MESSAGE_KINDS and symbol in _message_symbols(message):
                return candidate
    for candidate in messages:
        if _message_kind(candidate) in _BUSINESS_MESSAGE_KINDS:
            return candidate
    return messages[0]


def _format_price_list(values: Any) -> str | None:
    if isinstance(values, list):
        out: list[str] = []
        for value in values:
            try:
                out.append(f"{float(value):.2f}")
            except Exception:
                text = str(value or "").strip()
                if text:
                    out.append(text)
        return " / ".join(out) if out else None
    return None


def _range_from_zone(zone: Any) -> str | None:
    if not isinstance(zone, dict):
        return None
    low = zone.get("low")
    high = zone.get("high")
    mid = zone.get("mid") or zone.get("price")
    try:
        if low is not None and high is not None:
            return f"{float(low):.2f} - {float(high):.2f}"
        if mid is not None:
            return f"{float(mid):.2f}"
    except Exception:
        return None
    return None


def _candidate_pick_objects(message: Dict[str, Any]) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for key in ("pick", "live_check"):
        value = message.get(key)
        if isinstance(value, dict) and value:
            out.append(value)
    exit_value = message.get("exit_decision")
    if isinstance(exit_value, dict) and exit_value:
        take = _format_price_list(exit_value.get("take_profit"))
        out.append(
            {
                "symbol": exit_value.get("symbol"),
                "stop_text": exit_value.get("invalidation"),
                "take_text": take,
                "source_run_id": exit_value.get("source_run_id"),
            }
        )
    picks = message.get("picks")
    if isinstance(picks, list):
        out.extend(item for item in picks if isinstance(item, dict))
    run = message.get("run")
    if isinstance(run, dict):
        out.extend(item for item in (run.get("picks") or []) if isinstance(item, dict))
    return out


def _select_pick_fact(message: Dict[str, Any], frame: TurnFrame, memory_ctx: Dict[str, Any]) -> Dict[str, Any]:
    candidates = _candidate_pick_objects(message)
    if not candidates:
        return {}
    refs = frame.references or {}
    wanted_symbol = str(refs.get("symbol") or refs.get("focus_symbol") or getattr(memory_ctx["session"], "last_focus_symbol", None) or "").strip()
    wanted_rank = refs.get("rank") or getattr(memory_ctx["session"], "last_focus_rank", None)
    if wanted_symbol:
        for item in candidates:
            if str(item.get("symbol") or "").strip() == wanted_symbol:
                return dict(item)
    if wanted_rank is not None:
        for item in candidates:
            try:
                if int(item.get("rank")) == int(wanted_rank):
                    return dict(item)
            except Exception:
                continue
    return dict(candidates[0])


def _explain_grounded_fields(message: Dict[str, Any], pick: Dict[str, Any]) -> Dict[str, Any]:
    run = message.get("run") if isinstance(message.get("run"), dict) else {}
    entry_text = str(pick.get("entry_text") or "").strip() or _range_from_zone(pick.get("entry_zone"))
    stop_text = str(pick.get("stop_text") or pick.get("invalidation") or "").strip()
    take_text = str(pick.get("take_text") or "").strip() or _format_price_list(pick.get("take_profit"))
    return {
        "symbol": pick.get("symbol"),
        "rank": pick.get("rank"),
        "name": pick.get("name"),
        "thesis": pick.get("thesis"),
        "why_selected": pick.get("why_selected"),
        "entry_text": entry_text,
        "stop_text": stop_text,
        "take_text": take_text,
        "execution_state": pick.get("execution_state"),
        "source_run_id": pick.get("source_run_id") or run.get("run_id") or message.get("run_id"),
        "market_phase": run.get("market_phase"),
        "daybook_effective_day": run.get("daybook_effective_day"),
        "pulse_slot_at": run.get("pulse_slot_at"),
    }


def _extract_term_text(frame: TurnFrame) -> str:
    constraints = dict(frame.constraints or {})
    term = str(constraints.get("term_text") or "").strip()
    return term or str(frame.raw_message or "").strip()


def _term_explain_result(
    *,
    session_id: str,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
    frame: TurnFrame,
) -> AgentToolResult:
    latest = _find_term_explain_source(memory_ctx, frame)
    if not latest:
        latest = _latest_assistant_message(memory_ctx)
    message = dict(latest.get("message") or {})
    meta = dict(latest.get("meta") or {})
    term = _extract_term_text(frame)
    pick_fact = _select_pick_fact(message, frame, memory_ctx)
    grounded_fields = _explain_grounded_fields(message, pick_fact) if pick_fact else {}
    source_kind = message.get("message_kind") or meta.get("kind")
    reply_text = "我会基于最近一条结构化业务结论解释，不重新计算新的市场判断。"
    suggestions = ["这只现在还能买吗", "为什么暂不入场", "今天给我 3 只"]

    if grounded_fields:
        bits = []
        if grounded_fields.get("symbol"):
            bits.append(f"标的 {grounded_fields['symbol']}")
        if grounded_fields.get("entry_text"):
            bits.append(f"买入区 {grounded_fields['entry_text']}")
        if grounded_fields.get("stop_text"):
            bits.append(f"止损/失效 {grounded_fields['stop_text']}")
        if grounded_fields.get("take_text"):
            bits.append(f"止盈 {grounded_fields['take_text']}")
        if grounded_fields.get("execution_state"):
            bits.append(f"执行状态 {execution_state_label(str(grounded_fields['execution_state']))}")
        if bits:
            reply_text = "我会基于最近一条结构化业务结论解释：" + "；".join(bits) + "。"
        suggestions = ["这只现在还能买吗", "它的止盈止损点再说一遍", "为什么这样判断"]
    elif message.get("narrative_text"):
        reply_text = "我只找到了上一轮文本结论，缺少可核对的结构化计划字段；我会说明这一限制，不能补造计算公式。"
        suggestions = ["今天给我 3 只", "这只票为什么能上榜", "当前该看什么"]

    return AgentToolResult(
        tool_name="explain_followup",
        reply_text=reply_text,
        message={
            "message_kind": "term_explain",
            "narrative_text": reply_text,
            "term": term,
            "source_message_kind": source_kind,
            "source_symbol": grounded_fields.get("symbol"),
            "source_run_id": grounded_fields.get("source_run_id"),
            "grounded_fields": {key: value for key, value in grounded_fields.items() if value not in (None, "", [])},
            "source_narrative_text": message.get("narrative_text"),
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


def _assistant_context_result(book: MarketBook) -> AgentToolResult:
    intraday_enabled = intraday_runtime_enabled()
    reply_text = (
        "你好，我可以直接帮你看今天的候选、某只票还能不能买、止盈止损怎么设，或者解释上一条结论。"
        if intraday_enabled
        else "你好，我可以直接帮你看今天的候选、解释某只票为什么入选，或者说明当前该看什么。盘中运行链已关闭，仅使用日线计划模块。"
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
            "followup_suggestions": ["给我当前推荐的前三个标的", "这只票为什么能上榜", "今天适合空仓暂不入场还是执行计划"],
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


def _tool_call_name(tool_call: Dict[str, Any]) -> str:
    function = tool_call.get("function") or {}
    return str(function.get("name") or "").strip()


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


def _agent_tool_schemas() -> List[Dict[str, Any]]:
    def strict_tool(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
                "strict": True,
            },
        }

    def obj(properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        }

    return [
        strict_tool(
            name="get_market_context",
            description="Read the current market, session, active run and recent dialogue context before choosing a business action.",
            parameters=obj({"detail": {"type": "string", "description": "Why context is needed."}}),
        ),
        strict_tool(
            name="get_active_run",
            description="Read the current active recommendation run and top candidates.",
            parameters=obj({"top_n": {"type": "integer", "minimum": 1, "maximum": 10}}),
        ),
        strict_tool(
            name="recommend_current",
            description="Generate or refresh the current recommendation set, then evaluate it through the unified decision context and thesis lifecycle.",
            parameters=obj({"topk": {"type": "integer", "minimum": 1, "maximum": 10}}),
        ),
        strict_tool(
            name="analyze_symbol",
            description="Analyze whether a concrete A-share security forms a reasonable decision for the user context, including symbols outside the current run.",
            parameters=obj(
                {
                    "symbol": {"type": "string", "description": "Six digit A-share symbol."},
                    "question": {"type": "string"},
                },
                required=["symbol"],
            ),
        ),
        strict_tool(
            name="analyze_exit_decision",
            description=(
                "Analyze whether an existing holding should hold, reduce or sell. Use this for 持有、成本、卖点、"
                "止盈、止损、减仓、该不该卖、还能拿吗 questions."
            ),
            parameters=obj(
                {
                    "symbol": {"type": ["string", "null"], "description": "Six digit A-share symbol when known."},
                    "rank": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "position_context": {"type": "string", "description": "User-provided holding, cost, profit/loss and sell-point context."},
                },
            ),
        ),
        strict_tool(
            name="analyze_intraday_situation",
            description="Analyze user-provided intraday situation such as current price, high/low, volume, pullback,盘口 or news.",
            parameters=obj(
                {
                    "symbol": {"type": ["string", "null"], "description": "Six digit symbol when known."},
                    "rank": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "user_situation": {"type": "string", "description": "The user's intraday facts and question."},
                },
            ),
        ),
        strict_tool(
            name="compare_candidates",
            description="Compare active-run candidates under the user's objective and constraints. The downstream decision engine validates the action; do not use this as a fixed answer template.",
            parameters=obj(
                {
                    "symbols": {"type": "array", "items": {"type": "string"}},
                    "top_n": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "selected_symbol": {"type": ["string", "null"]},
                    "selected_rank": {"type": ["integer", "null"], "minimum": 1, "maximum": 10},
                    "selection_reason": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "user_constraint": {"type": "string"},
                    "model_reasoning_summary": {"type": "string"},
                },
            ),
        ),
        strict_tool(
            name="explain_run_change",
            description="Explain how the current recommendation run differs from the previous run.",
            parameters=obj({"question": {"type": "string"}}),
        ),
        strict_tool(
            name="answer_chat",
            description="Answer non-market chat or capability questions. Do not use this for candidate selection, intraday analysis, recommendation, comparison, buy/sell, or concrete stock analysis.",
            parameters=obj(
                {
                    "answer": {"type": "string"},
                    "reason": {"type": "string"},
                },
                required=["answer"],
            ),
        ),
    ]


def _agent_system_prompt() -> str:
    return (
        "你是 GP 的 A 股投资决策助手。你必须真实选择一个工具，而不是直接自由回答。"
        "所有买、卖、持有、加仓、减仓、等待、比较和复盘问题都要进入统一 Decision Intelligence 流程。"
        "工具用于构建 market/security/signal/user/position/objective/constraints 决策上下文，不是固定回答模板。"
        "你可以综合用户给出的盘中情况、当前榜单、历史上下文和通用股票常识选择合适决策工具。"
        "程序会校验工具白名单、候选范围、交易数据来源和会话落盘。"
        "如果用户说“聊天”“输出文字”，把它理解为输出形式偏好，不能覆盖市场任务。"
        "从前几个里挑科技股、防守股、更适合当前盘中情况的，都用 compare_candidates。"
        "问某只为什么不如第一只、和第几只比、谁更好、谁更适合买，都用 compare_candidates。"
        "问系统之前是否错了、为什么变化、之前判断还成立吗，用 explain_run_change 或相应单票/持仓工具进入 thesis lifecycle。"
        "用户问持有、成本、卖点、止盈、止损、减仓、该不该卖、还能不能拿时，用 analyze_exit_decision。"
        "用户给出现价、最高价、横住、回落、量能、盘口、消息等盘中事实时，用 analyze_intraday_situation。"
        "明确 6 位代码但不是盘中入场问题时，用 analyze_symbol。"
        "推荐当前机会用 recommend_current；解释本轮变化用 explain_run_change。"
        "只有问候、能力说明或非市场聊天才用 answer_chat。"
        "不要编造本地行情；用户提供的数据在工具结果中会被标成 user_provided/unverified。"
    )


def _json_load_arguments(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    function = tool_call.get("function") or {}
    raw = function.get("arguments")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    obj = json.loads(str(raw))
    if not isinstance(obj, dict):
        raise ValueError("tool arguments must be a JSON object")
    return obj


def _append_agent_tool_result(messages: List[Dict[str, Any]], assistant_step: Dict[str, Any], tool_call: Dict[str, Any], result: AgentToolResult | ReplyBundle) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": assistant_step.get("content"),
            "tool_calls": assistant_step.get("tool_calls") or [],
            **({"reasoning_content": assistant_step.get("reasoning_content")} if assistant_step.get("reasoning_content") else {}),
        }
    )
    payload = result.model_dump() if hasattr(result, "model_dump") else result
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call.get("id") or _tool_call_name(tool_call),
            "name": _tool_call_name(tool_call),
            "content": json.dumps(payload, ensure_ascii=False),
        }
    )


def _agent_context_result(memory_ctx: Dict[str, Any], book: MarketBook) -> AgentToolResult:
    context = build_agent_routing_context(memory_ctx, book)
    return AgentToolResult(
        tool_name="get_market_context",
        reply_text="已读取当前市场、会话和候选上下文。",
        message={
            "message_kind": "agent_context",
            "market": context.get("market") or {},
            "session_focus": {
                "session_focus_symbol": context.get("session_focus_symbol"),
                "focus_subject": (context.get("session") or {}).get("focus_subject"),
                "compare_set": (context.get("session") or {}).get("compare_set") or [],
            },
            "active_run": context.get("active_run") or {},
            "context_refs": context.get("context_refs") or [],
        },
        tool_trace={"context_keys": list(context.keys())},
    )


def _active_run_result(memory_ctx: Dict[str, Any], book: MarketBook, top_n: int = 6) -> AgentToolResult:
    context = build_agent_routing_context(memory_ctx, book)
    active_run = dict(context.get("active_run") or {})
    candidates = list(active_run.pop("candidate_summary", []) or [])
    if active_run.get("candidate_source") == "candidate_summary":
        candidates = list(context.get("candidate_summary") or [])
    candidates = candidates[: max(1, min(10, top_n))]
    run_id = active_run.get("run_id")
    return AgentToolResult(
        tool_name="get_active_run",
        reply_text="已读取当前 active run。" if active_run.get("available") else "当前会话没有 active run。",
        message={
            "message_kind": "active_run_context",
            "active_run": active_run,
            "candidate_summary": candidates,
            "context_refs": [
                ref
                for ref in list(context.get("context_refs") or [])
                if ref.get("run_id") == run_id or ref.get("symbol") in {item.get("symbol") for item in candidates}
            ],
        },
        run_id=run_id,
        symbols=[str(item.get("symbol")) for item in candidates if item.get("symbol")],
    )


def _frame_for_agent_tool(tool_name: str, args: Dict[str, Any], user_message: str, memory_ctx: Dict[str, Any]) -> TurnFrame:
    session = memory_ctx["session"]
    refs: Dict[str, Any] = {}
    constraints: Dict[str, Any] = {"allow_derived_data": True}
    request = "chat"
    subject = "market"
    if tool_name == "recommend_current":
        request = "recommend"
        subject = "run"
        constraints["topk"] = int(args.get("topk") or 3)
    elif tool_name == "analyze_symbol":
        request = "single_stock_query"
        subject = "symbol"
        refs["symbol"] = str(args.get("symbol") or "").strip()
    elif tool_name == "analyze_exit_decision":
        request = "exit_decision"
        subject = "holding"
        if args.get("symbol"):
            refs["symbol"] = str(args.get("symbol")).strip()
        if args.get("rank") is not None:
            refs["rank"] = args.get("rank")
        constraints["position_context"] = str(args.get("position_context") or user_message)
    elif tool_name == "analyze_intraday_situation":
        request = "intraday_situation"
        subject = "symbol"
        if args.get("symbol"):
            refs["symbol"] = str(args.get("symbol")).strip()
        elif getattr(session, "last_focus_symbol", None):
            refs["symbol"] = session.last_focus_symbol
        if args.get("rank") is not None:
            refs["rank"] = args.get("rank")
        constraints["user_situation"] = str(args.get("user_situation") or user_message)
    elif tool_name == "compare_candidates":
        request = "candidate_compare"
        subject = "compare_set"
        symbols = [str(symbol).strip() for symbol in (args.get("symbols") or []) if str(symbol).strip()]
        if symbols:
            refs["compare_symbols"] = symbols
        if args.get("selected_symbol"):
            refs["selected_symbol"] = str(args.get("selected_symbol")).strip()
        if args.get("selected_rank") is not None:
            refs["rank"] = args.get("selected_rank")
        for key in ("top_n", "selection_reason", "confidence", "user_constraint", "model_reasoning_summary"):
            if key in args:
                constraints[key] = args.get(key)
    elif tool_name == "explain_run_change":
        request = "run_change"
        subject = "run"
    return TurnFrame(
        frame_id=gen_id("frame"),
        raw_message=user_message,
        subject=subject,
        request=request,
        freshness="active_run",
        references=refs,
        constraints=constraints,
        ambiguity={"confidence": 0.8, "notes": [f"agent_tool:{tool_name}"], "needs_clarification": False},
    )


def _normalized_frame_for_agent_tool(
    tool_name: str,
    args: Dict[str, Any],
    user_message: str,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
) -> TurnFrame:
    frame = _frame_for_agent_tool(tool_name, args, user_message, memory_ctx)
    if tool_name == "analyze_symbol":
        frame = normalize_turn_frame(frame, book=book)
        frame = inject_entity_hints(frame, memory_ctx, book)
        return normalize_turn_frame(frame, book=book)
    return inject_entity_hints(frame, memory_ctx, book)


def _execute_domain_agent_tool(
    *,
    tool_name: str,
    args: Dict[str, Any],
    session_id: str,
    user_message: str,
    memory_ctx: Dict[str, Any],
    book: MarketBook,
    frame: TurnFrame | None = None,
) -> tuple[ReplyBundle | AgentToolResult, Judgment, bool]:
    if tool_name == "get_market_context":
        return _agent_context_result(memory_ctx, book), judge_chat(), False
    if tool_name == "get_active_run":
        return _active_run_result(memory_ctx, book, int(args.get("top_n") or 6)), judge_chat(), False
    if tool_name == "answer_chat":
        text = str(args.get("answer") or "").strip() or "可以直接问我今天的候选、某只票为什么入选、盘中还能不能进，或者当前该不该卖。"
        judgment = judge_chat()
        reply = ReplyBundle(
            session_id=session_id,
            text=text,
            kind="chat",
            message={"message_kind": "chat", "narrative_text": text, "followup_suggestions": ["今天给我 3 只", "看一下当前榜单", "某只票现在能买吗"]},
        )
        return reply, judgment, True

    frame = frame or _normalized_frame_for_agent_tool(tool_name, args, user_message, memory_ctx, book)
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
        recent_turns=list(memory_ctx.get("recent_turns") or []),
    )
    reply.tool_trace = {**dict(reply.tool_trace or {}), "agent_tool": tool_name, "agent_args": args}
    return reply, judgment, True


def _agent_tool_requires_market_ready(tool_name: str) -> bool:
    return tool_name in {"recommend_current", "analyze_intraday_situation", "compare_candidates", "analyze_exit_decision", "explain_run_change"}


def _agent_frame_requires_market_ready(frame: TurnFrame) -> bool:
    return frame.request not in {"chat", "term_explain", "single_stock_query"}


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

    client = LLMClient()
    try:
        ok, _ = client.available()
    except Exception:
        ok = False

    if not ok:
        raise IntentLLMUnavailable("LLM unavailable before agent tool selection")

    context = build_agent_routing_context(memory_ctx, book)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": _agent_system_prompt()},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "user_message": user_message,
                    "context": context,
                    "instruction": "Choose the next tool. Do not answer directly.",
                },
                ensure_ascii=False,
            ),
        },
    ]
    agent_tools = _agent_tool_schemas()
    routing_payload = {
        "model": getattr(client, "agent_model", "agent"),
        "messages": messages,
        "temperature": 0.0,
        "stream": False,
        "tools": agent_tools,
        "tool_choice": "required",
    }
    if serialized_size_bytes(routing_payload) > ROUTING_PAYLOAD_LIMIT_BYTES:
        context = compact_agent_routing_context(context)
        messages[1]["content"] = json.dumps(
            {
                "user_message": user_message,
                "context": context,
                "instruction": "Choose the next tool. Do not answer directly.",
            },
            ensure_ascii=False,
        )
    trace = AgentActionTrace(max_tool_rounds=max(1, int(getattr(load_config(), "agent_max_tool_rounds", 3) or 3)))
    active_judgment = judge_chat()
    active_reply: ReplyBundle | None = None
    try:
        for _round in range(trace.max_tool_rounds):
            if not (context.get("context_policy") or {}).get("secondary_compaction"):
                routing_payload = {
                    "model": getattr(client, "agent_model", "agent"),
                    "messages": messages,
                    "temperature": 0.0,
                    "stream": False,
                    "tools": agent_tools,
                    "tool_choice": "required",
                }
                if serialized_size_bytes(routing_payload) > ROUTING_PAYLOAD_LIMIT_BYTES:
                    context = compact_agent_routing_context(context)
                    messages[1]["content"] = json.dumps(
                        {
                            "user_message": user_message,
                            "context": context,
                            "instruction": "Choose the next tool. Do not answer directly.",
                        },
                        ensure_ascii=False,
                    )
            step = client.agent_tool_step(messages, agent_tools, tool_choice="required", temperature=0.0)
            if step.get("reasoning_content"):
                trace.reasoning_content_seen = True
            tool_calls = step.get("tool_calls") or []
            if not tool_calls:
                trace.stopped_reason = "missing_tool_call"
                raise RuntimeError("DeepSeek agent did not select a tool")
            tool_call = tool_calls[0]
            tool_name = _tool_call_name(tool_call)
            if tool_name not in {tool["function"]["name"] for tool in agent_tools}:
                trace.stopped_reason = "unknown_tool"
                raise RuntimeError(f"DeepSeek agent selected unknown tool: {tool_name}")
            args = _json_load_arguments(tool_call)
            trace.selected_tools.append(tool_name)
            frame = _normalized_frame_for_agent_tool(tool_name, args, user_message, memory_ctx, book)

            if _agent_tool_requires_market_ready(tool_name) or _agent_frame_requires_market_ready(frame):
                snapshot = load_repair_status_snapshot()
                if _repair_blocks_market_answers(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason):
                    market_ready = _market_ready_result(book, snapshot=snapshot, blocking_reason_override=repair_blocking_reason)
                    active_judgment = judge_chat()
                    active_reply = _bundle_from_tool_result(session_id, market_ready, text=market_ready.reply_text)
                    trace.final_tool = "ensure_market_ready"
                    trace.stopped_reason = "market_not_ready"
                    break

            result, active_judgment, terminal = _execute_domain_agent_tool(
                tool_name=tool_name,
                args=args,
                session_id=session_id,
                user_message=user_message,
                memory_ctx=memory_ctx,
                book=book,
                frame=frame,
            )
            _append_agent_tool_result(messages, step, tool_call, result)
            if terminal:
                if isinstance(result, ReplyBundle):
                    active_reply = result
                else:
                    active_reply = _bundle_from_tool_result(session_id, result, text=result.reply_text)
                trace.final_tool = tool_name
                trace.stopped_reason = "completed"
                break
        else:
            trace.stopped_reason = "tool_round_limit"
            raise RuntimeError("DeepSeek agent exceeded tool round limit")

        if active_reply is None:
            raise RuntimeError("DeepSeek agent did not produce a terminal business result")
        active_reply.agent_trace = trace.model_dump()
        active_reply.planner_trace = trace.model_dump()
        active_reply.message = {**dict(active_reply.message or {}), "agent_trace": trace.model_dump()}
        validate_reply(active_reply, active_judgment)
        commit_turn(session_id=session_id, user_message=user_message, reply=active_reply, judgment=active_judgment)
        return {
            "session_id": active_reply.session_id,
            "reply": active_reply.text,
            "message": active_reply.message,
            "run_id": active_reply.run_id,
            "symbols": active_reply.symbols,
            "right_panel": active_reply.right_panel,
            "ui_items": active_reply.ui_items,
            "grounding_summary": active_reply.grounding_summary,
            "planner_trace": active_reply.planner_trace,
        }
    except Exception as ex:
        trace.errors.append(f"{type(ex).__name__}: {ex}")
        logger.exception("[turn] deepseek agent failed without legacy fallback: %s", ex)
        raise


run_turn = run_turn_sync
