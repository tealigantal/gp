from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
import logging

from . import event_store
from . import session_store as store
from .assistant_bundle import AssistantBundle, Card
from .context_builder import build_turn_context
from .output_validators import (
    GroundingRequiredValidator,
    SymbolConsistencyValidator,
    TradeabilityConsistencyValidator,
)
from .tool_registry import build_registry
from ..core.errors import APIError
from ..llm.client import LLMClient

_log = logging.getLogger(__name__)


AGENT_SYSTEM_PROMPT = (
    "你是一个A股短线金融工作区的单一 Agent。\n"
    "所有与标的/推荐/交易相关的回答必须基于工具结果，不得编造。\n"
    "当 tradeable=false 或 run_gating.decision!=allow 时，严禁输出买入/建仓语义；仅可用于观察/阻断说明。\n"
    "如需用到推荐顺序（第一/第二/第三），严格按照 ensure_recommendation.items 的顺序。\n"
    "优先保证事实一致与可追溯，使用简洁中文回答。"
)

STRATEGY_EXPLANATIONS_PROMPT = (
    "策略解释（S1–S14）：\n"
    "- S1：BIAS6 上穿 BIAS12 的动量转强信号，提供关键带与确认/失效条件。\n"
    "- S2：RSI2 低位反转/极值回归类短线信号，关注超短反弹机会。\n"
    "- S3：波动收缩（Squeeze）形态，博弈收缩后的方向性释放。\n"
    "- S4：海龟汤（Turtle Soup）反转形态，围绕假突破后的反包机会。\n"
    "- S5：MA20 回撤与再上行的结构性买点，强调不追高、回踩确认。\n"
    "- S6：突破后回踩确认的趋势延续形态，强调结构稳定与承接。\n"
    "- S7：NR7 最小实体收缩形态，博弈收缩后的突破/趋势延续。\n"
    "- S8：量比放大与价量配合的动量型信号，关注放量不跌与承接质量。\n"
    "- S9：筹码支撑与成本带回收，利用低吸与支撑确认的结构性机会。\n"
    "- S10：缺口回补/高开回落等 Gap 衰退博弈，强调不追涨与风险控制。\n"
    "- S11：RSI2 极值扩展信号，相对 S2 更激进的超短反转博弈。\n"
    "- S12：锚定 VWAP（AVWAP）相关的均值与支撑阻力博弈，强调结构靠近成交重心。\n"
    "- S13：收缩后的释放（Squeeze Release）形态，关注放量突破与延续。\n"
    "- S14：海龟汤增强版（Turtle Soup Plus），结合更严格的反包/确认规则。\n\n"
    "当用户询问某个策略（如“S1是什么/解释S7/策略含义/适用场景/确认与失效条件”），请结合上述解释与工具结果，用简洁中文作答；涉及买入或建仓结论必须严格遵守 tradeable 与 gating 约束。"
)

TOOL_CONTRACT_PROMPT = (
    "TOOL CONTRACT:\n"
    "1. 金融相关问题（推荐、候选、比较、研究、止盈止损、卖出判断、6位股票代码）必须优先调用工具。\n"
    "2. 调用 ensure_recommendation 时，必须显式提供完整 JSON 参数："
    '{"session_id":"...", "topk":3, "refresh":true/false}。\n'
    "3. 不得传 null、空字符串、残缺 JSON。\n"
    "4. 若用户明确要求“强制刷新/刷新候选/最新数据/明天/下一交易日”，refresh 必须为 true。\n"
    "5. 若 tradeable=false 或 gating 不允许，不得输出买入/建仓结论。\n"
    "6. 纯策略解释类问题（如：S1/S7 是什么、策略含义/确认/失效条件）可直接回答，不必调用工具；一旦涉及具体标的/推荐/比较/盈亏比，则必须先走工具。\n"
    "7. 问候/闲聊/元问题（如：你好、如何使用、关于你）可直接简短回答，不必调用任何工具。"
)

TOOLING_FEWSHOT_PROMPT = (
    "示例：\n"
    "用户：明天 top 3\n"
    "动作：ensure_recommendation {session_id, topk:3, refresh:true}\n\n"
    "用户：强制刷新候选，用最新的数据 topk=5\n"
    "动作：ensure_recommendation {session_id, topk:5, refresh:true}\n\n"
    "用户：为什么是这只\n"
    "动作：get_pick_detail；必要时 explain_selection_set\n\n"
    "用户：可以 / 好的 / 行\n"
    "若 recent_user_texts 暗示是在承接出票/候选/推荐，则调用 ensure_recommendation {session_id, topk:3, refresh:true}\n\n"
    "用户：S1 是什么策略？\n"
    "动作：不调用工具，直接基于‘策略解释（S1–S14）’回答；若追问具体标的/比较/盈亏比，再按规则调用相关工具\n\n"
    "用户：你好\n"
    "动作：不调用工具，直接问候+简短可用功能提示"
)


def _tool_specs_full(strict: bool = False) -> List[Dict[str, Any]]:
    def fn(name: str, args_schema: Dict[str, Any]) -> Dict[str, Any]:
        spec: Dict[str, Any] = {
            "type": "function",
            "function": {
                "name": name,
                "parameters": args_schema,
            },
        }
        if strict:
            spec["function"]["strict"] = True
        return spec

    def obj_with_session(required_only: bool = True) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"] if required_only else [],
        }

    return [
        fn(
            "chat",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["session_id", "query"],
            },
        ),
        fn("get_session_context", obj_with_session(required_only=True)),
        fn(
            "ensure_recommendation",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "topk": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 3,
                    },
                    "refresh": {"type": "boolean", "default": False},
                },
                "required": ["session_id", "topk", "refresh"],
            },
        ),
        fn(
            "resolve_reference",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "raw_reference": {"type": "string"},
                },
                "required": ["session_id", "raw_reference"],
            },
        ),
        fn("explain_selection_set", obj_with_session(required_only=True)),
        fn(
            "get_pick_detail",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["session_id", "symbol"],
            },
        ),
        fn(
            "compare_symbols",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "symbols": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["session_id", "symbols"],
            },
        ),
        fn(
            "get_exit_decision",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["session_id", "symbol"],
            },
        ),
        fn("get_run_change", obj_with_session(required_only=True)),
        fn(
            "set_focus_symbol",
            {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "symbol": {"type": "string"},
                },
                "required": ["session_id", "symbol"],
            },
        ),
    ]


def _tool_specs_ctx_only(strict: bool = False) -> List[Dict[str, Any]]:
    tools: List[Dict[str, Any]] = []

    chat_spec: Dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "chat",
            "parameters": {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["session_id", "query"],
            },
        },
    }
    if strict:
        chat_spec["function"]["strict"] = True
    tools.append(chat_spec)

    ctx_spec: Dict[str, Any] = {
        "type": "function",
        "function": {
            "name": "get_session_context",
            "parameters": {
                "type": "object",
                "additionalProperties": False if strict else True,
                "properties": {
                    "session_id": {"type": "string"},
                },
                "required": ["session_id"],
            },
        },
    }
    if strict:
        ctx_spec["function"]["strict"] = True
    tools.append(ctx_spec)

    return tools


def _json_args(raw: Any) -> Dict[str, Any]:
    try:
        if isinstance(raw, str) and raw.strip():
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}


def _looks_like_strategy_explanation(text: Optional[str]) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    s_lower = s.lower()
    # S1..S14 mentions or generic strategy explanation words
    has_sid = bool(re.search(r"\bS\s*0?(?:[1-9]|1[0-4])\b", s, flags=re.IGNORECASE))
    keywords = ["策略", "是什么", "解释", "说明", "含义", "适用", "确认", "失效"]
    has_kw = any(k in s for k in keywords)
    # If contains obvious trade/stock cues, not pure explanation
    trade_cues = ["推荐", "买", "卖", "止盈", "止损", "比较", "刷新", "明天", "下一交易日", "top", "topk"]
    has_symbol = bool(re.search(r"\b\d{6}\b", s))
    has_trade = any(k in s for k in trade_cues) or has_symbol
    return (has_sid or has_kw) and not has_trade


def _looks_like_finance_action(text: Optional[str]) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    # Any explicit stock code or clear action-related keywords
    if re.search(r"\b\d{6}\b", s):
        return True
    cues = [
        "推荐",
        "候选",
        "top",
        "topk",
        "比较",
        "买",
        "卖",
        "止盈",
        "止损",
        "盈亏比",
        "RR",
        "强制刷新",
        "刷新",
        "明天",
        "下一交易日",
    ]
    return any(k.lower() in s.lower() for k in cues)


def _looks_like_small_talk(text: Optional[str]) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    lowers = s.lower()
    greetings = ["你好", "您好", "嗨", "早上好", "下午好", "晚上好", "hello", "hi", "hey"]
    meta = ["怎么用", "如何使用", "帮助", "help", "usage", "关于你", "你是谁"]
    if any(k in s for k in greetings):
        return True
    if any(k in s for k in meta) and not _looks_like_finance_action(s):
        return True
    return False


def _exec_tool(reg: Any, name: str, args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    sid = session_id

    if name == "chat":
        return reg.chat(sid, args.get("query") or "")
    if name == "get_session_context":
        return reg.get_session_context(sid)
    if name == "ensure_recommendation":
        return reg.ensure_recommendation(
            sid,
            topk=args.get("topk"),
            refresh=bool(args.get("refresh")),
        )
    if name == "resolve_reference":
        return reg.resolve_reference(sid, args.get("raw_reference") or "")
    if name == "explain_selection_set":
        return reg.explain_selection_set(sid)
    if name == "get_pick_detail":
        return reg.get_pick_detail(sid, args.get("symbol") or "")
    if name == "compare_symbols":
        return reg.compare_symbols(sid, args.get("symbols") or [])
    if name == "get_exit_decision":
        return reg.get_exit_decision(sid, args.get("symbol") or "")
    if name == "get_run_change":
        return reg.get_run_change(sid)
    if name == "set_focus_symbol":
        return reg.set_focus_symbol(sid, args.get("symbol") or "")

    raise ValueError(f"unknown tool: {name}")


def _append_tool_io(
    messages: List[Dict[str, Any]],
    call: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
    messages.append(
        {
            "role": "tool",
            "tool_call_id": call.get("id"),
            "content": json.dumps(result, ensure_ascii=False),
        }
    )


def _build_turn_ctx_snapshot(turn_ctx: Dict[str, Any]) -> Dict[str, Any]:
    state = turn_ctx.get("session_state") or {}
    recent_dialogue_all = turn_ctx.get("recent_dialogue") or []

    recent_user_texts = [
        d.get("text")
        for d in recent_dialogue_all
        if d.get("role") == "user" and isinstance(d.get("text"), str)
    ]
    recent_user_texts = [t[:120] for t in recent_user_texts][-3:]

    return {
        "session_state": {
            k: state.get(k)
            for k in [
                "active_run_id",
                "previous_run_id",
                "focus_symbol",
                "active_symbols",
                "pending_action",
                "pending_symbols",
                "pending_cursor",
            ]
        },
        "active_artifact_summary": {
            "active_run_id": (turn_ctx.get("active_artifact_summary") or {}).get("active_run_id"),
            "tradeable": (turn_ctx.get("active_artifact_summary") or {}).get("tradeable"),
            "ordered_symbols": (turn_ctx.get("active_artifact_summary") or {}).get("ordered_symbols"),
        },
        "recent_dialogue": [
            {
                "role": d.get("role"),
                "kind": d.get("kind"),
                "active_run_id": d.get("active_run_id"),
                "card_types": d.get("card_types") if d.get("role") == "assistant" else [],
            }
            for d in recent_dialogue_all[-6:]
        ],
        "recent_user_texts": recent_user_texts,
        "recent_tool_trace_summary": (
            turn_ctx.get("recent_tool_trace_summary")[-3:]
            if isinstance(turn_ctx.get("recent_tool_trace_summary"), list)
            else []
        ),
        "continuation_state": turn_ctx.get("continuation_state") or {},
    }


def _build_messages(user_message: str, ctx_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "system", "content": STRATEGY_EXPLANATIONS_PROMPT},
        {"role": "system", "content": TOOL_CONTRACT_PROMPT},
        {"role": "system", "content": TOOLING_FEWSHOT_PROMPT},
        {
            "role": "system",
            "content": f"turn_context: {json.dumps(ctx_snapshot, ensure_ascii=False)}",
        },
        {"role": "user", "content": user_message},
    ]


def _persist_bundle_and_return(
    sid: str,
    text: str,
    cards: List[Card],
    right_panel: Dict[str, Any],
    tool_calls_trace: List[Dict[str, Any]],
    tool_results_trace: List[Dict[str, Any]],
    grounding: Dict[str, Any],
) -> Dict[str, Any]:
    bundle = AssistantBundle.build(
        conversation_id=sid,
        text=text,
        cards=cards,
        right_panel=right_panel,
        tool_calls=tool_calls_trace,
        tool_results=tool_results_trace,
        grounding=grounding,
    )
    payload = bundle.to_payload()

    ev_id = f"ab-{sid}-{store._now_iso()}"  # type: ignore[attr-defined]
    event_store.append_event(
        sid,
        event_id=ev_id,
        type="message.created",
        data={
            "message_id": ev_id,
            "kind": "assistant_bundle",
            "content": "",
            "payload": payload,
        },
        actor_id="assistant",
    )

    try:
        last_bundle_summary = {
            "text_head": (payload.get("text") or "")[:160],
            "card_types": [
                str((c or {}).get("type") or "")
                for c in (payload.get("cards") or [])
                if isinstance(c, dict)
            ],
            "active_run_id": (payload.get("right_panel") or {}).get("active_run_id"),
        }
        last_tool_summary = {
            "tools_used": list((payload.get("grounding") or {}).get("tools_used") or []),
            "used_symbols": list((payload.get("grounding") or {}).get("used_symbols") or []),
            "active_run_id": (payload.get("right_panel") or {}).get("active_run_id")
            or (payload.get("grounding") or {}).get("active_run_id"),
            "tradeable": (payload.get("grounding") or {}).get("tradeable"),
        }

        updates: Dict[str, Any] = {
            "last_right_panel": payload.get("right_panel"),
            "last_surface_kind": "assistant_bundle",
            "last_visible_assistant_summary": last_bundle_summary,
            "last_tool_results_summary": last_tool_summary,
        }

        rr = next((r for r in tool_results_trace if r.get("tool") == "resolve_reference"), None)
        if rr:
            updates["last_reference_resolution"] = rr.get("output")

        store.update_state(sid, updates)
    except Exception:
        pass

    return {
        "session_id": sid,
        "reply": text,
        "right_panel": right_panel,
    }


def run_agent_turn(session_id: Optional[str], user_message: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", user_message)
    try:
        _log.info("chat.receive session_id=%s message=%s", sid, user_message)
    except Exception:
        pass

    reg = build_registry()
    llm = LLMClient()
    strict = True

    ok, reason = llm.available()
    try:
        _log.info("llm.available ok=%s reason=%s session_id=%s", ok, reason, sid)
    except Exception:
        pass
    if not ok:
        raise APIError(
            status_code=503,
            message="LLM_NOT_CONFIGURED",
            detail={"provider": "deepseek", "reason": reason},
        )

    turn_ctx = build_turn_context(sid)
    state = turn_ctx.get("session_state") or {}
    ctx_snapshot = _build_turn_ctx_snapshot(turn_ctx)

    messages = _build_messages(user_message, ctx_snapshot)

    # Intent hints for tool gating
    is_small_talk = _looks_like_small_talk(user_message)
    allow_no_tool_reply = is_small_talk or _looks_like_strategy_explanation(user_message)
    require_tools = _looks_like_finance_action(user_message) and not allow_no_tool_reply

    tool_calls_trace: List[Dict[str, Any]] = []
    tool_results_trace: List[Dict[str, Any]] = []

    # Step 1: chat / get_session_context
    step1_tools = _tool_specs_ctx_only(strict) if require_tools else []
    try:
        _log.info("llm.request.start phase=step1 session_id=%s", sid)
    except Exception:
        pass
    try:
        # For small-talk or pure explanation, do not force or expose tools
        step1_tool_choice = "required" if require_tools else None
        msg_step1 = llm.run_chat_with_tools(messages, step1_tools, tool_choice=step1_tool_choice)
        try:
            tc = msg_step1.get("tool_calls") if isinstance(msg_step1, dict) else None
            names = [str((c.get("function") or {}).get("name")) for c in (tc or []) if isinstance(c, dict)]
            _log.info(
                "llm.request.success phase=step1 session_id=%s tool_calls=%s intent=%s",
                sid,
                len(tc) if isinstance(tc, list) else 0,
                ",".join(names),
            )
        except Exception:
            pass
    except Exception:
        _log.exception("llm.request.failed phase=step1 session_id=%s", sid)
        raise

    if not (
        isinstance(msg_step1, dict)
        and isinstance(msg_step1.get("tool_calls"), list)
        and msg_step1.get("tool_calls")
    ):
        # Only allow early text return when it's pure strategy explanation or small-talk
        if allow_no_tool_reply and isinstance(msg_step1, dict):
            final_text = _sanitize_model_text(msg_step1.get("content") or "")
            return _persist_bundle_and_return(
                sid=sid,
                text=final_text,
                cards=[],
                right_panel={},
                tool_calls_trace=[],
                tool_results_trace=[],
                grounding={
                    "source": "deepseek_tool_calling_finance_agent",
                    "tools_used": [],
                },
            )
        # Else: proceed to step2 to enforce tool grounding

    for call in msg_step1["tool_calls"]:
        name = (call.get("function") or {}).get("name")
        raw = (call.get("function") or {}).get("arguments") or "{}"
        args = _json_args(raw)
        try:
            _log.info("tool.call.start tool=%s phase=step1 session_id=%s", name, sid)
        except Exception:
            pass
        if name == "chat":
            if not args.get("query"):
                args["query"] = user_message
            try:
                result = reg.chat(sid, args.get("query") or "")
            except Exception:
                _log.exception("tool.call.failed tool=chat phase=step1 session_id=%s", sid)
                raise
        else:
            try:
                result = _exec_tool(reg, name, args, sid)
            except Exception:
                _log.exception("tool.call.failed tool=%s phase=step1 session_id=%s", name, sid)
                raise
        try:
            _log.info("tool.call.success tool=%s phase=step1 session_id=%s", name, sid)
        except Exception:
            pass
        
        tool_calls_trace.append({"tool": name, "args": args})
        tool_results_trace.append({"tool": name, "output": result})
        _append_tool_io(messages, call, result)

    # Step 2: full tools (only when required)
    full_tools = _tool_specs_full(strict) if require_tools else []
    final_text: Optional[str] = None

    for i in range(3):
        try:
            _log.info("llm.request.start phase=step2 iter=%s session_id=%s", i + 1, sid)
        except Exception:
            pass
        try:
            # Allow direct answer if small-talk/pure explanation; otherwise require tool calls
            tool_choice_value = "required" if require_tools else None
            msg = llm.run_chat_with_tools(messages, full_tools, tool_choice=tool_choice_value)
            try:
                tc = msg.get("tool_calls") if isinstance(msg, dict) else None
                _log.info(
                    "llm.request.success phase=step2 iter=%s session_id=%s tool_calls=%s",
                    i + 1,
                    sid,
                    len(tc) if isinstance(tc, list) else 0,
                )
            except Exception:
                pass
        except Exception:
            _log.exception("llm.request.failed phase=step2 iter=%s session_id=%s", i + 1, sid)
            raise
        calls = msg.get("tool_calls") if isinstance(msg, dict) else None

        if calls:
            for call in calls:
                name = (call.get("function") or {}).get("name")
                raw = (call.get("function") or {}).get("arguments") or "{}"
                args = _json_args(raw)

                if name == "ensure_recommendation":
                    if "refresh" not in args:
                        raise APIError(
                            status_code=400,
                            message="INVALID_TOOL_ARGS",
                            detail={"tool": "ensure_recommendation", "missing": ["refresh"]},
                        )

                try:
                    try:
                        _log.info("tool.call.start tool=%s phase=step2 session_id=%s", name, sid)
                    except Exception:
                        pass
                    result = _exec_tool(reg, name, args, sid)
                    try:
                        _log.info("tool.call.success tool=%s phase=step2 session_id=%s", name, sid)
                    except Exception:
                        pass
                except APIError as e:
                    tool_calls_trace.append({"tool": name, "args": args})
                    tool_results_trace.append(
                        {
                            "tool": name,
                            "error": getattr(e, "message", "INVALID_TOOL_ARGS"),
                            "detail": getattr(e, "detail", {}),
                        }
                    )
                    return _persist_bundle_and_return(
                        sid=sid,
                        text=f"错误：{getattr(e, 'message', 'INVALID_TOOL_ARGS')}（{getattr(e, 'detail', {})}）",
                        cards=[],
                        right_panel={},
                        tool_calls_trace=tool_calls_trace,
                        tool_results_trace=tool_results_trace,
                        grounding={
                            "source": "deepseek_tool_calling_finance_agent",
                            "tools_used": [t.get("tool") for t in tool_calls_trace],
                        },
                    )

                tool_calls_trace.append({"tool": name, "args": args})
                tool_results_trace.append({"tool": name, "output": result})
                _append_tool_io(messages, call, result)

            continue

        final_text = _sanitize_model_text(
            msg.get("content") if isinstance(msg, dict) else ""
        )
        break

    if final_text is None:
        try:
            _log.info("llm.request.start phase=final_fallback session_id=%s", sid)
        except Exception:
            pass
        try:
            msg_final = llm.run_chat_with_tools(messages, tools=[])
            try:
                _log.info("llm.request.success phase=final_fallback session_id=%s", sid)
            except Exception:
                pass
        except Exception:
            _log.exception("llm.request.failed phase=final_fallback session_id=%s", sid)
            raise
        final_text = _sanitize_model_text(
            msg_final.get("content") if isinstance(msg_final, dict) else ""
        )

    tradeable = None
    run_gating = None
    allowed_symbols: List[str] = []

    for tr in tool_results_trace:
        if tr.get("tool") == "ensure_recommendation":
            out = tr.get("output") or {}
            tradeable = out.get("tradeable")
            run_gating = out.get("run_gating")
            items = out.get("items") or []
            allowed_symbols.extend(
                [
                    str((it or {}).get("symbol") or "")
                    for it in items
                    if isinstance(it, dict) and (it or {}).get("symbol")
                ]
            )

        if tr.get("tool") == "explain_selection_set":
            out = tr.get("output") or {}
            allowed_symbols.extend([str(s) for s in (out.get("selection_set_symbols") or [])])

    last_validation_error: Optional[str] = None
    try:
        explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
        ensure_called = any(r.get("tool") == "ensure_recommendation" for r in tool_results_trace)

        if not allowed_symbols and not ensure_called:
            allowed_symbols = list(
                {
                    str(s)
                    for s in (state.get("active_symbols") or [])
                    if s
                }
            )

        SymbolConsistencyValidator(
            final_text=final_text or "",
            cards=[],
            allowed_symbols=list({s for s in allowed_symbols if s}),
            user_explicit_symbols=explicit_syms,
        )
        TradeabilityConsistencyValidator(
            tradeable=tradeable,
            run_gating=run_gating,
            final_text=final_text or "",
            cards=[],
        )
        GroundingRequiredValidator(tool_results=tool_results_trace)
    except Exception as e:
        last_validation_error = str(e)
        messages.append(
            {
                "role": "system",
                "content": "你的上一条回复违反约束。请严格基于上方工具结果，输出简洁、合规、可追溯的中文答案。",
            }
        )
        msg_final = llm.run_chat_with_tools(messages, tools=[])
        final_text = _sanitize_model_text(
            msg_final.get("content") if isinstance(msg_final, dict) else ""
        )

        try:
            explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
            SymbolConsistencyValidator(
                final_text=final_text or "",
                cards=[],
                allowed_symbols=list(set(allowed_symbols)),
                user_explicit_symbols=explicit_syms,
            )
            TradeabilityConsistencyValidator(
                tradeable=tradeable,
                run_gating=run_gating,
                final_text=final_text or "",
                cards=[],
            )
            GroundingRequiredValidator(tool_results=tool_results_trace)
        except Exception as e2:
            last_validation_error = str(e2) or last_validation_error or "validation_failed"
            final_text = f"错误：{last_validation_error}。本轮已记录工具结果与状态。"

    right_panel: Dict[str, Any] = {}
    active_run_id = None
    active_symbols: List[str] = []
    as_of = None
    reused_run = None
    refresh_reason = None
    cards: List[Card] = []

    for tr in tool_results_trace:
        if tr.get("tool") == "ensure_recommendation":
            out = tr.get("output") or {}
            active_run_id = out.get("active_run_id")
            tradeable = out.get("tradeable")
            run_gating = out.get("run_gating")
            as_of = out.get("as_of")
            reused_run = out.get("reused_run")
            refresh_reason = out.get("refresh_reason")
            items = out.get("items") or []

            active_symbols = [
                str((it or {}).get("symbol") or "")
                for it in items
                if isinstance(it, dict) and (it or {}).get("symbol")
            ]

            right_panel = {
                "active_run_id": active_run_id,
                "active_symbols": active_symbols,
                "tradeable": tradeable,
                "run_gating": run_gating,
                "reused_run": reused_run,
                "refresh_reason": refresh_reason,
            }

            mode = "tradeable_recommendation" if bool(tradeable) else "observe_only_selection"
            card_data = {
                "active_run_id": active_run_id,
                "as_of": as_of,
                "tradeable": tradeable,
                "run_gating": run_gating,
                "items": [
                    {
                        "symbol": (it or {}).get("symbol"),
                        "name": (it or {}).get("name"),
                        "label": (it or {}).get("strategy_label") or (it or {}).get("strategy"),
                        "rank": idx + 1,
                        "actionable": (it or {}).get("actionable"),
                        "gating_decision": (it or {}).get("gating_decision"),
                    }
                    for idx, it in enumerate(items)
                    if isinstance(it, dict)
                ],
                "mode": mode,
            }

            cards.append(
                Card(
                    "recommendation",
                    "推荐清单",
                    card_data,
                    symbols=active_symbols,
                    run_id=str(active_run_id or ""),
                )
            )

            if tradeable is False:
                reasons: List[str] = []
                if isinstance(run_gating, dict):
                    dec = run_gating.get("decision")
                    if dec:
                        reasons.append(str(dec))
                    rs = run_gating.get("reasons") or []
                    if isinstance(rs, list):
                        reasons.extend([str(x) for x in rs])
                if out.get("reason"):
                    reasons.append(str(out.get("reason")))
                if not reasons:
                    reasons = ["RUN_NOT_TRADEABLE"]
                final_text = f"错误：RUN_NOT_TRADEABLE（{'; '.join(reasons)}）"

    for tr in tool_results_trace:
        if tr.get("tool") == "explain_selection_set":
            ex = tr.get("output") or {}
            cards.append(
                Card(
                    "selection_explain",
                    "入选说明",
                    {
                        "selection_set_symbols": ex.get("selection_set_symbols")
                        or ex.get("top_symbols")
                        or [],
                        "ranking_rationale": ex.get("ranking_rationale"),
                        "mode": ex.get("mode"),
                    },
                    symbols=ex.get("selection_set_symbols") or [],
                )
            )

        if tr.get("tool") == "get_pick_detail":
            d = tr.get("output") or {}
            sym = d.get("symbol")
            if sym:
                cards.append(Card("pick_detail", f"标的 {sym}", d, focus_symbol=str(sym)))

        if tr.get("tool") == "get_exit_decision":
            d = tr.get("output") or {}
            sym = None
            pd = next((r for r in tool_results_trace if r.get("tool") == "get_pick_detail"), None)
            if pd:
                sym = (pd.get("output") or {}).get("symbol")
            cards.append(
                Card(
                    "exit_decision",
                    f"卖出判断 {sym or ''}",
                    d,
                    focus_symbol=(str(sym) if sym else None),
                )
            )

        if tr.get("tool") == "get_run_change":
            rc = tr.get("output") or {}
            cards.append(
                Card(
                    "run_change",
                    "推荐变化说明",
                    rc,
                    symbols=(rc.get("added_symbols") or []) + (rc.get("removed_symbols") or []),
                )
            )

    if not right_panel:
        try:
            rp0 = state.get("last_right_panel") or {}
            if isinstance(rp0, dict) and rp0:
                right_panel = dict(rp0)
                active_run_id = active_run_id or rp0.get("active_run_id")
                active_symbols = active_symbols or list(rp0.get("active_symbols") or [])
                if tradeable is None:
                    tradeable = rp0.get("tradeable")
                run_gating = run_gating or rp0.get("run_gating")
        except Exception:
            pass

    grounding = {
        "source": "deepseek_tool_calling_finance_agent",
        "active_run_id": active_run_id,
        "previous_run_id": store.get_state(sid).get("previous_run_id"),
        "focus_symbol": store.get_focus(sid),
        "active_symbols": active_symbols,
        "used_symbols": list(set(allowed_symbols)),
        "tradeable": tradeable,
        "run_gating": run_gating,
        "reused_run": reused_run,
        "refresh_reason": refresh_reason,
        "tools_used": [t.get("tool") for t in tool_calls_trace],
    }

    return _persist_bundle_and_return(
        sid=sid,
        text=final_text or "",
        cards=cards,
        right_panel=right_panel,
        tool_calls_trace=tool_calls_trace,
        tool_results_trace=tool_results_trace,
        grounding=grounding,
    )


def _sanitize_model_text(text: Optional[str]) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    # 去掉 DeepSeek / DSML 一类内嵌标签
    s = re.sub(r"<[^>]*DSML[^>]*>[\s\S]*?</[^>]*DSML[^>]*>", "", s, flags=re.IGNORECASE)

    # 去掉各种奇怪尖括号包裹标记
    s = re.sub(r"<\|.*?\|>", "", s)
    s = re.sub(r"<｜.*?｜>", "", s)

    # 去掉 fenced json
    s = re.sub(r"```json[\s\S]*?```", "", s, flags=re.IGNORECASE)

    # 去掉 function_call / tool_calls 片段
    s = re.sub(r'\{\s*"function_call"[\s\S]*?\}\s*', "", s)
    s = re.sub(r'\{\s*"tool_calls"[\s\S]*?\}\s*', "", s)

    # 去掉裸露的 XML/HTML 风格工具标签
    s = re.sub(r"</?(tool|function|call|analysis)[^>]*>", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()
