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


SYSTEM_PROMPT = (
    "你是一个A股短线金融工作区的单一DeepSeek Agent。"
    "每轮必须先读取session上下文(get_session_context)。与当前run/当前symbol/selection set/上一轮变化相关的问题，必须先调用工具获取事实。"
    "没有有效工具结果，不允许输出金融结论。不得发明不在工具结果中的symbol、entry、stop、take、RR、tradeable、run_gating、action。"
    "当tradeable=false或run_gating.decision!=allow时：不得建议买入/建仓，也不得把item说成BUY；只能解释候选观察/排序/阻断。"
    "非金融元问题（如你是谁/系统如何工作）可直接回答，但不得混入金融结论。不得存在第二条自由金融回答线路。"
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
        fn("get_session_context", obj_optional),
        fn("ensure_recommendation", {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": {
                "session_id": {"type": "string"},
                "topk": {"type": ["integer", "null"]},
                "refresh": {"type": ["boolean", "null"]},
            },
            "required": ["session_id"],
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
    return [o]


def _exec_tool(reg, name: str, args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
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


def run_agent_turn(session_id: Optional[str], user_message: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", user_message)

    reg = build_registry()
    llm = LLMClient()
    strict = True  # default to strict tool schema

    # Production fail-closed: DeepSeek not configured -> controlled error
    ok, reason = llm.available()
    if not ok:
        raise APIError(status_code=503, message="LLM_NOT_CONFIGURED", detail={"provider": "deepseek", "reason": reason})

    # Step 0: load state + recent bundle summaries (not raw legacy text)
    turn_ctx = build_turn_context(sid)
    state = turn_ctx.get("session_state") or {}
    recent_bundles = turn_ctx.get("recent_bundles") or []

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"session_state: {json.dumps(state, ensure_ascii=False)}"},
        {"role": "system", "content": f"recent_bundles: {json.dumps(recent_bundles, ensure_ascii=False)}"},
        {"role": "user", "content": user_message},
    ]

    tool_calls_trace: List[Dict[str, Any]] = []
    tool_results_trace: List[Dict[str, Any]] = []

    # Step 1: force get_session_context only
    step1_tools = _tool_specs_ctx_only(strict)
    msg1 = llm.run_chat_with_tools(messages, step1_tools)
    if not (isinstance(msg1, dict) and isinstance(msg1.get("tool_calls"), list) and msg1.get("tool_calls")):
        # Fail-safe: do not allow free text here
        raise RuntimeError("model_did_not_call_get_session_context")

    for call in msg1.get("tool_calls"):
        nm = (call.get("function") or {}).get("name")
        raw = (call.get("function") or {}).get("arguments") or "{}"
        try:
            args = json.loads(raw)
        except Exception:
            args = {}
        res = _exec_tool(reg, nm, args, sid)
        tool_calls_trace.append({"tool": nm, "args": args})
        tool_results_trace.append({"tool": nm, "output": res})
        messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(res, ensure_ascii=False)})

    # Step 2: full tools, up to 3 rounds
    tools_full = _tool_specs_full(strict)
    final_text: Optional[str] = None
    for _ in range(3):
        msg = llm.run_chat_with_tools(messages, tools_full)
        calls = msg.get("tool_calls") if isinstance(msg, dict) else None
        if calls:
            for call in calls:
                nm = (call.get("function") or {}).get("name")
                raw = (call.get("function") or {}).get("arguments") or "{}"
                try:
                    args = json.loads(raw)
                except Exception:
                    args = {}
                res = _exec_tool(reg, nm, args, sid)
                tool_calls_trace.append({"tool": nm, "args": args})
                tool_results_trace.append({"tool": nm, "output": res})
                messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": json.dumps(res, ensure_ascii=False)})
            continue
        # no tool_calls -> final answer
        final_text = msg.get("content") if isinstance(msg, dict) else None
        break

    if final_text is None:
        # Give the model one last chance to produce final reply without tools
        msg_final = llm.run_chat_with_tools(messages, tools=[])
        final_text = msg_final.get("content") if isinstance(msg_final, dict) else ""

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
    try:
        # extract explicit symbols from user text
        import re
        explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
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
    except Exception:
        # Retry once with a stricter instruction to use tool results only
        messages.append({"role": "system", "content": "你的上一条回答违反约束。请仅基于上面的工具结果生成简洁合规的回答，不要杜撰。"})
        msg_final = llm.run_chat_with_tools(messages, tools=[])
        final_text = msg_final.get("content") if isinstance(msg_final, dict) else ""
        # second pass validation; on failure, fall back to guarded message
        try:
            import re
            explicit_syms = re.findall(r"\b(\d{6})\b", user_message or "")
            SymbolConsistencyValidator(final_text=final_text or "", cards=[], allowed_symbols=list(set(allowed_symbols)), user_explicit_symbols=explicit_syms)
            TradeabilityConsistencyValidator(tradeable=tradeable, run_gating=run_gating, final_text=final_text or "", cards=[])
            GroundingRequiredValidator(tool_results=tool_results_trace)
        except Exception:
            final_text = "抱歉，当前无法生成合规的金融回复。请根据卡片与事实自行判断。"

    # Compose right panel and canonical cards from tool results
    right_panel = {}
    active_run_id = None
    active_symbols = []
    as_of = None
    tradeable = None
    run_gating = None
    cards: List[Dict[str, Any]] = []
    for tr in tool_results_trace:
        if tr.get("tool") == "ensure_recommendation":
            out = tr.get("output") or {}
            active_run_id = out.get("active_run_id")
            tradeable = out.get("tradeable")
            run_gating = out.get("run_gating")
            as_of = out.get("as_of")
            items = out.get("items") or []
            active_symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
            right_panel = {
                "active_run_id": active_run_id,
                "active_symbols": active_symbols,
                "tradeable": tradeable,
                "run_gating": run_gating,
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
            # no_trade card when non-tradeable
            if tradeable is False:
                cards.append(Card("no_trade", "今日不交易", {
                    "tradeable": False,
                    "run_gating": run_gating,
                    "reason": out.get("reason"),
                    "warnings": (run_gating or {}).get("warnings"),
                    "reasons": (run_gating or {}).get("reasons"),
                }, run_id=str(active_run_id or "")))

    # selection_explain card
    for tr in tool_results_trace:
        if tr.get("tool") == "explain_selection_set":
            ex = tr.get("output") or {}
            cards.append(Card("selection_explain", "入选说明", {
                "selection_set_symbols": ex.get("selection_set_symbols") or ex.get("top_symbols") or [],
                "per_symbol_rationale": ex.get("per_symbol_rationale"),
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
            cards.append(Card("run_change", "本轮变更", rc, symbols=(rc.get("added_symbols") or []) + (rc.get("removed_symbols") or [])))

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
        store.update_state(sid, {"last_right_panel": payload.get("right_panel")})
    except Exception:
        pass

    return {"session_id": sid, "reply": final_text or "", "right_panel": right_panel}
