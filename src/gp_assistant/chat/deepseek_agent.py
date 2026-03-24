from __future__ import annotations

from typing import Any, Dict, List, Optional
import json

from . import session_store as store
from . import event_store
from .assistant_bundle import AssistantBundle, Card
from .tool_registry import build_registry
from .output_validators import (
    SymbolConsistencyValidator,
    TradeabilityConsistencyValidator,
    GroundingRequiredValidator,
)
from .context_builder import build_turn_context
from ..llm.client import LLMClient
from ..core.errors import APIError


# Clean Chinese system prompt (avoid mojibake in older text)
AGENT_SYSTEM_PROMPT = (
    "你是一个A股短线金融工作区的单一 DeepSeek Agent。\n"
    "所有与标的/推荐/交易相关的回答必须基于工具结果，不得编造。\n"
    "当 tradeable=false 或 run_gating.decision!=allow 时，严禁输出买入/建仓语义；仅可用于观察/阻断说明。\n"
    "如需用到推荐顺序（第一/第二/第三），严格按照 ensure_recommendation.items 的顺序。\n"
    "优先保证事实一致与可追溯，使用简洁中文回答。"
)

SYSTEM_PROMPT = (
    "你是一个A股短线金融工作区的单一DeepSeek Agent。\n"
    "所有与标的/推荐/交易相关的结论必须基于工具结果，不得杜撰。\n"
    "当 tradeable=false 或 gating 未允许时，不给出买入/建仓结论；可以做观察与解释。\n"
    "如需用到推荐顺序（第一/第二/第三），严格按照 ensure_recommendation.items 的顺序。\n"
    "可以在保证荐股内容完整的前提下扩充一些内容。"
    "非金融/元问题可直接回答。\n"
    "如果用户仅回复'可以'/'好的'/'行'等确认类短语，结合最近用户文本(recent_user_texts)理解其承接含义：若与选股/候选有关，则直接发起 ensure_recommendation。\n"
    "当用户询问策略 sXX（如 s07）是什么，请参考下方‘策略术语表’用中文做简洁解释。\n"
    "\n"
    "【策略术语表】\n"
    "- s01：BIAS6 上穿 BIAS12 的动量转强信号，提供关键带与确认/失效条件。\n"
    "- s02：RSI2 低位反转/极值回归类短线信号，关注超短反弹机会。\n"
    "- s03：波动收缩（Squeeze）形态，博弈收缩后的方向性释放。\n"
    "- s04：海龟汤（Turtle Soup）反转形态，围绕假突破后的反包机会。\n"
    "- s05：MA20 回撤与再上行的结构性买点，强调不追高、回踩确认。\n"
    "- s06：突破后回踩确认的趋势延续形态，强调结构稳定与承接。\n"
    "- s07：NR7 最小实体收缩形态，博弈收缩后的突破/趋势延续。\n"
    "- s08：量比放大与价量配合的动量型信号，关注放量不跌与承接质量。\n"
    "- s09：筹码支撑与成本带回收，利用低吸与支撑确认的结构性机会。\n"
    "- s10：缺口回补/高开回落等 Gap 衰退博弈，强调不追涨与风险控制。\n"
    "- s11：RSI2 极值扩展信号，相对 s02 更激进的超短反转博弈。\n"
    "- s12：锚定 AVWAP 相关的均值与支撑阻力博弈，强调结构靠近成交重心。\n"
    "- s13：收缩后的释放（Squeeze Release）形态，关注放量突破与延续。\n"
    "- s14：海龟汤增强版（Turtle Soup Plus），结合更严格的反包/确认规则。\n"
    "术语表可以自行根据你的理解扩充一下解释"
)


def _tool_specs_full(strict: bool = False) -> List[Dict[str, Any]]:
    def fn(name: str, args_schema: Dict[str, Any]) -> Dict[str, Any]:
        o = {"type": "function", "function": {"name": name, "parameters": args_schema}}
        if strict:
            o["function"]["strict"] = True
        return o

    obj = {
        "type": "object",
        "additionalProperties": False if strict else True,
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
    }
    obj_optional = {
        "type": "object",
        "additionalProperties": False if strict else True,
        "properties": {"session_id": {"type": "string"}},
        "required": ["session_id"],
    }
    return [
        fn("chat", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {
                "session_id": {"type": "string"},
                "query": {"type": "string"},
            },
            "required": ["session_id", "query"],
        }),
        fn("get_session_context", obj_optional),
        fn("ensure_recommendation", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {
                "session_id": {"type": "string"},
                "topk": {"type": "integer", "minimum": 1, "maximum": 20, "default": 3},
                "refresh": {"type": "boolean", "default": False},
            },
            "required": ["session_id", "topk", "refresh"],
        }),
        fn("resolve_reference", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {
                "session_id": {"type": "string"},
                "raw_reference": {"type": "string"},
            },
            "required": ["session_id", "raw_reference"],
        }),
        fn("explain_selection_set", obj_optional),
        fn("get_pick_detail", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {"session_id": {"type": "string"}, "symbol": {"type": "string"}},
            "required": ["session_id", "symbol"],
        }),
        fn("compare_symbols", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {"session_id": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}}},
            "required": ["session_id", "symbols"],
        }),
        fn("get_exit_decision", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {"session_id": {"type": "string"}, "symbol": {"type": "string"}},
            "required": ["session_id", "symbol"],
        }),
        fn("get_run_change", obj_optional),
        fn("set_focus_symbol", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {"session_id": {"type": "string"}, "symbol": {"type": "string"}},
            "required": ["session_id", "symbol"],
        }),
    ]


def _tool_specs_ctx_only(strict: bool = False) -> List[Dict[str, Any]]:
    """Build minimal tool spec for the first round (chat/context only)."""
    # Entry tools: allow chat or get_session_context
    tools: List[Dict[str, Any]] = []
    for name in ("chat", "get_session_context"):
        if name == "chat":
            o = {
                "type": "function",
                "function": {
                    "name": "chat",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False if strict else True,
                        "properties": {"session_id": {"type": "string"}, "query": {"type": "string"}},
                        "required": ["session_id", "query"],
                    },
                },
            }
            if strict:
                o["function"]["strict"] = True
            tools.append(o)
        else:
            o = {
                "type": "function",
                "function": {
                    "name": "get_session_context",
                    "parameters": {
                        "type": "object",
                        "additionalProperties": False if strict else True,
                        "properties": {"session_id": {"type": "string"}},
                        "required": ["session_id"],
                    },
                },
            }
            if strict:
                o["function"]["strict"] = True
            tools.append(o)
    return tools


def _json_args(raw: Any) -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> Dict[str, Any]:
    """Parse tool arguments JSON into a dict (safe fallback to {})."""
    try:
        if isinstance(raw, str) and raw.strip():
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {}
def _exec_tool(reg, name: str, args: Dict[str, Any], session_id: str) -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> Dict[str, Any]:
    """Execute a registry tool deterministically (session_id enforced)."""
    # Always enforce session_id from runtime
    sid = session_id
    if name == "get_session_context":
        return reg.get_session_context(sid)
    if name == "ensure_recommendation":
        return reg.ensure_recommendation(sid, topk=args.get("topk"), refresh=bool(args.get("refresh")))
    if name == "resolve_reference":
        return reg.resolve_reference(sid, args.get("raw_reference") or "")
    if name == "explain_selection_set":
        return reg.explain_selection_set(sid)
    if name == "get_pick_detail":
        return reg.get_pick_detail(sid, args.get("symbol") or "")
    if name == "compare_symbols":
        syms = args.get("symbols") or []
        return reg.compare_symbols(sid, syms)
    if name == "get_exit_decision":
        return reg.get_exit_decision(sid, args.get("symbol") or "")
    if name == "get_run_change":
        return reg.get_run_change(sid)
    if name == "set_focus_symbol":
        return reg.set_focus_symbol(sid, args.get("symbol") or "")
    raise ValueError(f"unknown tool: {name}")


def run_agent_turn(session_id: Optional[str], user_message: str) -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> Dict[str, Any]:
    """Single agent turn: prompt -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> tools -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> compose -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> persist bundle.

    Behavior preserved; internals streamlined for readability.
    """
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", user_message)

    reg = build_registry()
    llm = LLMClient()
    strict = True  # default to strict tool schema

    # Production fail-closed: DeepSeek not configured -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> controlled error
    ok, reason = llm.available()
    if not ok:
        raise APIError(status_code=503, message="LLM_NOT_CONFIGURED", detail={"provider": "deepseek", "reason": reason})

    # Step 0: load state + recent bundle summaries (not raw legacy text)
    turn_ctx = build_turn_context(sid)
    state = turn_ctx.get("session_state") or {}
    # Compact a small context snapshot for LLM without dumping full history
    # Build compact, layered snapshot. Include a few recent user texts for pragmatic intent carryover.
    recent_dialogue_all = turn_ctx.get("recent_dialogue") or []
    recent_user_texts = [d.get("text") for d in recent_dialogue_all if d.get("role") == "user" and isinstance(d.get("text"), str)]
    recent_user_texts = [t[:120] for t in recent_user_texts][-3:]

    ctx_snapshot = {
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
                "card_types": (d.get("card_types") if d.get("role") == "assistant" else []),
            }
            for d in (turn_ctx.get("recent_dialogue") or [])[-6:]
        ],
        "recent_user_texts": recent_user_texts,
        "recent_tool_trace_summary": turn_ctx.get("recent_tool_trace_summary")[-3:] if isinstance(turn_ctx.get("recent_tool_trace_summary"), list) else [],
        "continuation_state": turn_ctx.get("continuation_state") or {},
    }

    # Remove legacy prompt constants from module namespace to avoid confusion
    try:
        AGENT_SYSTEM_PROMPT = None  # type: ignore[assignment]
        SYSTEM_PROMPT = None  # type: ignore[assignment]
        # Remove names entirely
        del AGENT_SYSTEM_PROMPT
        del SYSTEM_PROMPT
    except Exception:
        pass

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": "你是一个A股短线金融工作区的单一 DeepSeek Agent。\n所有与标的/推荐/交易相关的回答必须基于工具结果，不得编造。\n当 tradeable=false 或 run_gating.decision!=allow 时，严禁输出买入/建仓语义；仅可用于观察/阻断说明。\n如需用到推荐顺序（第一/第二/第三），严格按照 ensure_recommendation.items 的顺序。\n优先保证事实一致与可追溯，使用简洁中文回答。"},
        {"role": "system", "content": "TOOLING: For finance intents (picks/compare/exit/6-digit symbols), call tools (ensure_recommendation/resolve_reference/get_pick_detail/...). For future phrasing (tomorrow/next trading day), treat as next-session baseline; prefer ensure_recommendation and set refresh/topk appropriately."},
        {"role": "system", "content": "TOOLING-ZH: 当用户明确说出‘强制刷新/刷新候选/用最新数据/最新’或‘明天/下一交易日’，必须调用 ensure_recommendation {refresh:true, topk: 提取的数字或3}；不要复用当前 run；先输出工具结果（候选/顺序/可交易与否/理由），再做解释。"},
        {"role": "system", "content": "TOOLING-ZH: 当用户明确提到‘强制刷新/刷新候选/用最新数据/最新’或‘明天/下一交易日’，必须调用 ensure_recommendation {refresh:true, topk: 提取到的数字或3}；不得复用当前 run；先输出工具结果（候选/顺序/可交易与否/理由），再进行解释性文字。"},
        {"role": "system", "content": f"turn_context: {json.dumps(ctx_snapshot, ensure_ascii=False)}"},
        {"role": "system", "content": "FEW1: user says: tomorrow pick top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call ensure_recommendation {topk:3, refresh:true}; return grounded summary without buy/sell words if tradeable=false."},
        {"role": "system", "content": "FEW2: user says: next trading day candidates -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call ensure_recommendation {refresh:true}; optionally call explain_selection_set; answer with items and gating reasons."},
        {"role": "system", "content": "FEW3: user says: why this symbol -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call get_pick_detail (and/or explain_selection_set); answer with grounded rationale only."},
        {"role": "system", "content": "FEW4-ZH: 用户说: 可以/好的/行 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 若最近用户文本暗示要出候选/推荐，调用 ensure_recommendation {topk:3, refresh:true}，然后组织回答。"},
        {"role": "system", "content": "FEW-ZH1: 用户说: 强制刷新候选，用最新的数据，topk=5 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:5, refresh:true}；基于工具结果输出候选、顺序与 gating 原因，不得编造。"},
        {"role": "system", "content": "FEW-ZH2: 用户说: 明天的候选 top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:3, refresh:true}；必要时调用 explain_selection_set；若 tradeable=false，禁止买卖措辞，仅做观察/说明。"},
        {"role": "system", "content": "FEW4: user says: 可以/好的/行 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> if recent_user_texts imply picks/recommendation, call ensure_recommendation {topk:3, refresh:true} and then compose."},
        {"role": "system", "content": "FEW-ZH1: 用户说: 强制刷新候选，用最新的数据，topk=5 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:5, refresh:true}；基于工具结果输出候选、顺序与 gating 原因，不得凭空编造。"},
        {"role": "system", "content": "FEW-ZH2: 用户说: 明天的候选 top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:3, refresh:true}；必要时调用 explain_selection_set；若 tradeable=false，禁止买卖措辞，仅做观察/说明。"},
        {"role": "user", "content": user_message},
    ]

    # Clean and de-duplicate system instructions (remove garbled/duplicate TOOLING/FEW lines)
    messages = [
        {"role": "system", "content": "你是一个A股短线金融工作区的单一 DeepSeek Agent。\n所有与标的/推荐/交易相关的回答必须基于工具结果，不得编造。\n当 tradeable=false 或 run_gating.decision!=allow 时，严禁输出买入/建仓语义；仅可用于观察/阻断说明。\n如需用到推荐顺序（第一/第二/第三），严格按照 ensure_recommendation.items 的顺序。\n优先保证事实一致与可追溯，使用简洁中文回答。"},
        {"role": "system", "content": "TOOLING: For finance intents (picks/compare/exit/6-digit symbols), call tools (ensure_recommendation/resolve_reference/get_pick_detail/...). For future phrasing (tomorrow/next trading day), treat as next-session baseline; prefer ensure_recommendation and set refresh/topk appropriately."},
        {"role": "system", "content": "TOOLING-ZH: 当用户明确说出‘强制刷新/刷新候选/用最新数据/最新’或‘明天/下一交易日’，必须调用 ensure_recommendation {refresh:true, topk: 提取的数字或3}；不要复用当前 run；先输出工具结果（候选/顺序/可交易与否/理由），再做解释。"},
        {"role": "system", "content": f"turn_context: {json.dumps(ctx_snapshot, ensure_ascii=False)}"},
        {"role": "system", "content": "FEW1: user says: tomorrow pick top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call ensure_recommendation {topk:3, refresh:true}; return grounded summary without buy/sell words if tradeable=false."},
        {"role": "system", "content": "FEW2: user says: next trading day candidates -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call ensure_recommendation {refresh:true}; optionally call explain_selection_set; answer with items and gating reasons."},
        {"role": "system", "content": "FEW3: user says: why this symbol -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> call get_pick_detail (and/or explain_selection_set); answer with grounded rationale only."},
        {"role": "system", "content": "FEW4: user says: 可以/好的/行 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> if recent_user_texts imply picks/recommendation, call ensure_recommendation {topk:3, refresh:true} and then compose."},
        {"role": "system", "content": "FEW-ZH1: 用户说: 强制刷新候选，用最新的数据，topk=5 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:5, refresh:true}；基于工具结果输出候选、顺序与 gating 原因，不得编造。"},
        {"role": "system", "content": "FEW-ZH2: 用户说: 明天的候选 top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> 调用 ensure_recommendation {topk:3, refresh:true}；必要时调用 explain_selection_set；若 tradeable=false，禁止买卖措辞，仅做观察/说明。"},
        {"role": "user", "content": user_message},
    ]
    # Override messages with a clean tool contract to reduce ambiguity
    messages = [
        {"role": "system", "content": "你是一个A股短线金融工作区的单一 Agent。所有与标的/推荐/交易相关的回答必须基于工具结果，不得编造。当 tradeable=false 或 run_gating.decision!=allow 时，严禁输出买入/建仓语义；仅可做观察/阻断说明。"},
        {"role": "system", "content": "TOOL CONTRACT: 调用 ensure_recommendation 时，必须显式提供 JSON 参数：{ session_id: string, topk: integer[1..20], refresh: boolean }。不得传 null/空字符串/不完整 JSON。不确定 topk 时用 3。用户明确要求强制刷新/下一交易日/最新数据时，refresh 必须为 true。"},
        {"role": "system", "content": f"turn_context: {json.dumps(ctx_snapshot, ensure_ascii=False)}"},
        {"role": "system", "content": "FEW1: user: 明天 top 3 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> ensure_recommendation {topk:3, refresh:true}"},
        {"role": "system", "content": "FEW2: user: 强制刷新候选，用最新的数据 topk=5 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> ensure_recommendation {topk:5, refresh:true}"},
        {"role": "system", "content": "FEW3: user: 为什么是这只 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> get_pick_detail；如需补充集合依据 -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> explain_selection_set"},
        {"role": "user", "content": user_message},
    ]
    tool_calls_trace: List[Dict[str, Any]] = []
    tool_results_trace: List[Dict[str, Any]] = []

    # Step 1: entry tools (chat or get_session_context). Require a tool when supported.
    step1_tools = _tool_specs_ctx_only(strict)
    msg_step1 = llm.run_chat_with_tools(messages, step1_tools, tool_choice="required")
    if not (isinstance(msg_step1, dict) and isinstance(msg_step1.get("tool_calls"), list) and msg_step1.get("tool_calls")):
        # 接收第一阶段的纯文本并直接回复（提示：严格工具模式已启用；遇到金融意图会自动调用工具）
        final_text: Optional[str] = (msg_step1.get("content") if isinstance(msg_step1, dict) else None) or ""
        final_text = _sanitize_model_text(final_text)
        # Persist minimal assistant bundle and return
        bundle = AssistantBundle.build(
            conversation_id=sid,
            text=final_text or "",
            cards=[],
            right_panel={},
            tool_calls=[],
            tool_results=[],
            grounding={"source": "deepseek_tool_calling_finance_agent", "tools_used": []},
        )
        payload = bundle.to_payload()
        ev_id = f"ab-{sid}-{store._now_iso()}"  # type: ignore[attr-defined]
        event_store.append_event(
            sid,
            event_id=ev_id,
            type="message.created",
            data={"message_id": ev_id, "kind": "assistant_bundle", "content": "", "payload": payload},
            actor_id="assistant",
        )
        try:
            store.update_state(sid, {"last_right_panel": payload.get("right_panel")})
        except Exception:
            pass
        return {"session_id": sid, "reply": final_text or "", "right_panel": {}}

    for call in msg_step1.get("tool_calls"):
        nm = (call.get("function") or {}).get("name")
        raw = (call.get("function") or {}).get("arguments") or "{}"
        args = _json_args(raw)
        if nm == "chat":
            # Ensure query defaults to user_message when omitted
            a = dict(args or {})
            if not a.get("query"):
                a["query"] = user_message
            res = reg.chat(sid, a.get("query") or "")
        else:
            res = _exec_tool(reg, nm, args, sid)
            tool_calls_trace.append({"tool": nm, "args": args})
            tool_results_trace.append({"tool": nm, "output": res})
            messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(res, ensure_ascii=False)})

    # Step 2: full tools, up to 3 rounds
    full_tools = _tool_specs_full(strict)
    final_text: Optional[str] = None
    for _ in range(3):
        msg = llm.run_chat_with_tools(messages, full_tools, tool_choice="required")
        calls = msg.get("tool_calls") if isinstance(msg, dict) else None
        if calls:
            try:
                needs_retry = False
                for call in calls:
                    nm_pre = (call.get("function") or {}).get("name")
                    raw_pre = (call.get("function") or {}).get("arguments") or "{}"
                    if nm_pre == "ensure_recommendation":
                        a_pre = _json_args(raw_pre)
                        if not isinstance(a_pre, dict) or ("refresh" not in a_pre):
                            needs_retry = True
                            break
                if needs_retry:
                    # Do not auto-retry; surface as explicit error via assistant bundle by raising
                    raise APIError(status_code=400, message="INVALID_TOOL_ARGS", detail={"tool": "ensure_recommendation", "missing": ["refresh"]})
            except Exception:
                pass

            for call in calls:
                  nm = (call.get("function") or {}).get("name")
                  raw = (call.get("function") or {}).get("arguments") or "{}"
                  args = _json_args(raw)
                  try:
                      res = _exec_tool(reg, nm, args, sid)
                  except APIError as e:
                      tool_calls_trace.append({"tool": nm, "args": args})
                      tool_results_trace.append({"tool": nm, "error": getattr(e, "message", "INVALID_TOOL_ARGS"), "detail": getattr(e, "detail", {})})
                      bundle = AssistantBundle.build(
                          conversation_id=sid,
                          text=f"错误：{getattr(e, 'message', 'INVALID_TOOL_ARGS')}（{getattr(e, 'detail', {})}）",
                          cards=[],
                          right_panel={},
                          tool_calls=tool_calls_trace,
                          tool_results=tool_results_trace,
                          grounding={"source": "deepseek_tool_calling_finance_agent", "tools_used": [t.get("tool") for t in tool_calls_trace]},
                      )
                      payload = bundle.to_payload()
                      ev_id = f"ab-{sid}-{store._now_iso()}"
                      event_store.append_event(
                          sid,
                          event_id=ev_id,
                          type="message.created",
                          data={"message_id": ev_id, "kind": "assistant_bundle", "content": "", "payload": payload},
                          actor_id="assistant",
                      )
                      try:
                          store.update_state(sid, {"last_right_panel": payload.get("right_panel")})
                      except Exception:
                          pass
                      return {"session_id": sid, "reply": payload.get("text") or "", "right_panel": {}}
                  tool_calls_trace.append({"tool": nm, "args": args})
                  tool_results_trace.append({"tool": nm, "output": res})
                  messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                  messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(res, ensure_ascii=False)})
            continue
        # no tool_calls -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> final answer
        final_text = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(final_text, str):
            final_text = _sanitize_model_text(final_text)
        break

    if final_text is None:
        # Give the model one last chance to produce final reply without tools
        msg_final = llm.run_chat_with_tools(messages, tools=[])
        final_text = msg_final.get("content") if isinstance(msg_final, dict) else ""
        final_text = _sanitize_model_text(final_text)

    # No automatic refresh enforcement here; rely on tool arguments provided by the model.

    # Extract tradeable/run_gating/allowed symbols from tool results
    tradeable = None
    run_gating = None
    allowed_symbols: List[str] = []
    for tr in tool_results_trace:
        if tr.get("tool") == "ensure_recommendation":
            out = tr.get("output") or {}
            tradeable = out.get("tradeable")
            run_gating = out.get("run_gating")
            items = out.get("items") or []
            allowed_symbols.extend([str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")])
        if tr.get("tool") == "explain_selection_set":
            out = tr.get("output") or {}
            allowed_symbols.extend([str(s) for s in (out.get("selection_set_symbols") or [])])

    # Validate
    last_validation_error: Optional[str] = None
    try:
        # extract explicit symbols from user text
        import re
        explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
        # Fallback to session active symbols when no ensure_recommendation was called in this turn
        ensure_called = any((r.get("tool") == "ensure_recommendation") for r in tool_results_trace)
        if (not allowed_symbols) and (not ensure_called):
            allowed_symbols = list(set([str(s) for s in (state.get("active_symbols") or []) if s]))
        SymbolConsistencyValidator(
            final_text=final_text or "",
            cards=[],
            allowed_symbols=list(set([s for s in allowed_symbols if s])),
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
        # Retry once with a stricter instruction to use tool results only
        messages.append({"role": "system", "content": "Your previous reply violated constraints. Please produce a concise, compliant answer strictly based on the tool results above."})
        msg_final = llm.run_chat_with_tools(messages, tools=[])
        final_text = msg_final.get("content") if isinstance(msg_final, dict) else ""
        final_text = _sanitize_model_text(final_text)
        # second pass validation; on failure, fall back to guarded message
        try:
            import re
            explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
            SymbolConsistencyValidator(final_text=final_text or "", cards=[], allowed_symbols=list(set(allowed_symbols)), user_explicit_symbols=explicit_syms)
            TradeabilityConsistencyValidator(tradeable=tradeable, run_gating=run_gating, final_text=final_text or "", cards=[])
            GroundingRequiredValidator(tool_results=tool_results_trace)
        except Exception as e2:
            # Do not produce兜底；直接报错并携带错误码/原因
            last_validation_error = str(e2) or last_validation_error or "validation_failed"
            final_text = f"错误：{last_validation_error}。本轮已记录工具结果与状态。"

    # Compose right panel and canonical cards from tool results
    right_panel = {}
    active_run_id = None
    active_symbols = []
    as_of = None
    tradeable = None
    run_gating = None
    reused_run = None
    refresh_reason = None
    cards: List[Dict[str, Any]] = []
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
            active_symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
            right_panel = {
                "active_run_id": active_run_id,
                "active_symbols": active_symbols,
                "tradeable": tradeable,
                "run_gating": run_gating,
                "reused_run": reused_run,
                "refresh_reason": refresh_reason,
            }
            # recommendation card
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
            cards.append(Card("recommendation", "推荐清单", card_data, symbols=active_symbols, run_id=str(active_run_id or "")))
            # 不再展示“今日不交易”卡片；改为在文本层报错
            if tradeable is False:
                try:
                    reasons = []
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
                except Exception:
                    final_text = "错误：RUN_NOT_TRADEABLE。"

    # selection_explain card
    for tr in tool_results_trace:
        if tr.get("tool") == "explain_selection_set":
            ex = tr.get("output") or {}
            ex = tr.get("output") or {}
            cards.append(Card("selection_explain", "入选说明", {
                "selection_set_symbols": ex.get("selection_set_symbols") or ex.get("top_symbols") or [],
                "ranking_rationale": ex.get("ranking_rationale"),
                "mode": ex.get("mode"),
            }, symbols=ex.get("selection_set_symbols") or []))

    # pick_detail / exit_decision cards
    for tr in tool_results_trace:
        if tr.get("tool") == "get_pick_detail":
            d = tr.get("output") or {}
            sym = d.get("symbol")
            if sym:
                cards.append(Card("pick_detail", f"标的 {sym}", d, focus_symbol=str(sym)))
        if tr.get("tool") == "get_exit_decision":
            d = tr.get("output") or {}
            sym = None
            try:
                pd = next((r for r in tool_results_trace if r.get("tool") == "get_pick_detail"), None)
                if pd:
                    sym = (pd.get("output") or {}).get("symbol")
            except Exception:
                pass
            cards.append(Card("exit_decision", f"卖出判断 {sym or ''}", d, focus_symbol=(str(sym) if sym else None)))

    # run_change card
    for tr in tool_results_trace:
        if tr.get("tool") == "get_run_change":
            rc = tr.get("output") or {}
            cards.append(Card("run_change", "推荐变化说明", rc, symbols=(rc.get("added_symbols") or []) + (rc.get("removed_symbols") or [])))

    # Fallback right panel from session if empty (preserve continuity)
    if not right_panel:
        try:
            rp0 = (state.get("last_right_panel") or {})
            if isinstance(rp0, dict) and rp0:
                right_panel = dict(rp0)
                active_run_id = active_run_id or rp0.get("active_run_id")
                active_symbols = active_symbols or list(rp0.get("active_symbols") or [])
                tradeable = tradeable if (tradeable is not None) else rp0.get("tradeable")
                run_gating = run_gating or rp0.get("run_gating")
        except Exception:
            pass

    # Build and persist bundle
    bundle = AssistantBundle.build(
        conversation_id=sid,
        text=final_text or "",
        cards=cards,
        right_panel=right_panel,
        tool_calls=tool_calls_trace,
        tool_results=tool_results_trace,
        grounding={
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
        },
    )
    payload = bundle.to_payload()
    ev_id = f"ab-{sid}-{store._now_iso()}"  # type: ignore[attr-defined]
    event_store.append_event(
        sid,
        event_id=ev_id,
        type="message.created",
        data={"message_id": ev_id, "kind": "assistant_bundle", "content": "", "payload": payload},
        actor_id="assistant",
    )
    try:
        # Update layered session memory
        last_bundle_summary = {
            "text_head": (payload.get("text") or "")[:160],
            "card_types": [str((c or {}).get("type") or "") for c in (payload.get("cards") or []) if isinstance(c, dict)],
            "active_run_id": (payload.get("right_panel") or {}).get("active_run_id"),
        }
        last_tool_summary = {
            "tools_used": list((payload.get("grounding") or {}).get("tools_used") or []),
            "used_symbols": list((payload.get("grounding") or {}).get("used_symbols") or []),
            "active_run_id": (payload.get("right_panel") or {}).get("active_run_id") or (payload.get("grounding") or {}).get("active_run_id"),
            "tradeable": (payload.get("grounding") or {}).get("tradeable"),
        }
        updates: Dict[str, Any] = {
            "last_right_panel": payload.get("right_panel"),
            "last_surface_kind": "assistant_bundle",
            "last_visible_assistant_summary": last_bundle_summary,
            "last_tool_results_summary": last_tool_summary,
        }
        # Persist last reference resolution if present in tool results
        try:
            rr = next((r for r in tool_results_trace if r.get("tool") == "resolve_reference"), None)
            if rr:
                updates["last_reference_resolution"] = rr.get("output")
        except Exception:
            pass
        store.update_state(sid, updates)
    except Exception:
        pass

    return {"session_id": sid, "reply": final_text or "", "right_panel": right_panel}


def _sanitize_model_text(text: Optional[str]) -<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> str:
    """Remove DSML or tool markers accidentally surfaced in assistant content.

    DeepSeek sometimes returns content blocks like <｜ ... ｜<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> or raw function_calls JSON
    in the text field. Strip these patterns to avoid leaking internals.
    """
    s = (text or "")
    import re

    # Remove <｜ ... ｜<[\\|\\uFF5C][^>]*[\\|\\uFF5C]> style blocks
    s = re.sub(r"<[\\|\\uFF5C][^>]*[\\|\\uFF5C]>|<[\\|\\uFF5C][^>]*[\\|\\uFF5C]>|<[\\|\\uFF5C][^>]*[\\|\\uFF5C]s = re.sub(r"<[\|\uFF5C][^>]*[\|\uFF5C]>", "", s)\n    try:\n        s = re.sub(r"<[^>]*DSML[^>]*>[\\s\\S]*?</[^>]*DSML[^>]*>", "", s, flags=re.IGNORECASE)\n    except Exception:\n        pass
    # Remove fenced JSON blocks that look like function_calls
    s = re.sub(r"```json[\s\S]*?```", "", s)
    # Remove obvious 'function_call' JSON snippets inline
    s = re.sub(r"\{\s*\"function_call\"[\s\S]*?\}\s*", "", s)
    # Collapse excessive whitespace
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()









