from __future__ import annotations

from typing import Any, Dict, List, Optional

from .assistant_bundle import AssistantBundle
from .tool_registry import build_registry
from .output_validators import (
    SymbolConsistencyValidator,
    TradeabilityConsistencyValidator,
    GroundingRequiredValidator,
)
from . import session_store as store
from . import event_store


SYSTEM_PROMPT = (
    "你是一个A股短线金融工作区的单一Agent。所有与标的/推荐/交易相关的回答，必须基于工具结果，不得凭空杜撰。"
    "在每轮开始先读取session上下文；随后可调用高层工具（get_session_context, ensure_recommendation, resolve_reference, "
    "explain_selection_set, get_pick_detail, compare_symbols, get_exit_decision, get_run_change, set_focus_symbol）。"
    "若工具显示tradeable=false或run_gating.decision!=allow，则不得输出任何买入/建仓语义；仅可解释候选/观察/阻断。"
    "非金融元问题（如系统如何工作）可直接回答，但不得混入金融结论。"
)


class ToolCallingFinanceAgent:
    def __init__(self) -> None:
        self.registry = build_registry()

    def _deterministic_plan(self, user_message: str) -> Dict[str, Any]:
        # Lightweight planning purposefully not reliant on keyword routing.
        # Always ground to session + recommendation; attempt reference resolution.
        return {
            "tools": [
                {"name": "get_session_context", "args": {}},
                {"name": "ensure_recommendation", "args": {"topk": None, "refresh": False}},
                {"name": "resolve_reference", "args": {"raw_reference": user_message}},
            ]
        }

    def _execute_tools(self, session_id: str, plan: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for step in plan.get("tools", []) or []:
            nm = step.get("name")
            args = step.get("args") or {}
            if nm == "get_session_context":
                res = self.registry.get_session_context(session_id)
                out.append({"tool": nm, "args": args, "output": res})
            elif nm == "ensure_recommendation":
                res = self.registry.ensure_recommendation(session_id, topk=args.get("topk"), refresh=bool(args.get("refresh")) )
                out.append({"tool": nm, "args": args, "output": res})
            elif nm == "resolve_reference":
                res = self.registry.resolve_reference(session_id, args.get("raw_reference") or "")
                out.append({"tool": nm, "args": args, "output": res})
            else:
                # ignore unknown in this phase
                continue

        # Potential follow-ups based on reference results
        try:
            ref = next((r for r in out if r.get("tool") == "resolve_reference"), None)
            rec = next((r for r in out if r.get("tool") == "ensure_recommendation"), None)
            st = next((r for r in out if r.get("tool") == "get_session_context"), None)
            if ref and rec:
                r = ref.get("output") or {}
                if r.get("symbol"):
                    sym = str(r.get("symbol"))
                    out.append({"tool": "get_pick_detail", "args": {"symbol": sym}, "output": self.registry.get_pick_detail(session_id, sym)})
                    out.append({"tool": "get_exit_decision", "args": {"symbol": sym}, "output": self.registry.get_exit_decision(session_id, sym)})
                elif r.get("resolution_type") == "selection_set":
                    out.append({"tool": "explain_selection_set", "args": {}, "output": self.registry.explain_selection_set(session_id)})
                else:
                    # No concrete symbol resolved -> still add selection explanation to ground follow-up replies
                    out.append({"tool": "explain_selection_set", "args": {}, "output": self.registry.explain_selection_set(session_id)})
        except Exception:
            pass

        return out

    def _compose_text(self, tool_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Compose grounded reply text and cards based on available tool outputs.
        text = []
        cards: List[Dict[str, Any]] = []
        right_panel: Dict[str, Any] = {}
        tradeable = None
        run_gating = None
        active_run_id = None
        active_symbols: List[str] = []

        # extract basics
        try:
            rec = next((r for r in tool_results if r.get("tool") == "ensure_recommendation"), None)
            if rec:
                data = rec.get("output") or {}
                active_run_id = data.get("active_run_id")
                tradeable = data.get("tradeable")
                run_gating = data.get("run_gating")
                items = data.get("items") or []
                active_symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
                cards.append({
                    "type": "recommendation",
                    "items": items,
                })
                if tradeable is False:
                    text.append("当前为NO-TRADE日，以下为候选观察/排序解释。")
                else:
                    text.append("已生成推荐清单。")
        except Exception:
            pass

        try:
            sel = next((r for r in tool_results if r.get("tool") == "explain_selection_set"), None)
            if sel:
                s = sel.get("output") or {}
                top = s.get("top_symbols") or []
                if top:
                    text.append(f"Top: {', '.join([str(x) for x in top])}")
        except Exception:
            pass

        try:
            pd = next((r for r in tool_results if r.get("tool") == "get_pick_detail"), None)
            if pd:
                d = pd.get("output") or {}
                sym = d.get("symbol")
                thesis = d.get("thesis")
                if sym:
                    text.append(f"标的 {sym}: {thesis or '研究摘要可见卡片'}")
                    cards.append({"type": "pick_detail", "symbol": sym, "item": d})
        except Exception:
            pass

        try:
            ed = next((r for r in tool_results if r.get("tool") == "get_exit_decision"), None)
            if ed:
                d = ed.get("output") or {}
                sym = None
                try:
                    pd = next((r for r in tool_results if r.get("tool") == "get_pick_detail"), None)
                    if pd:
                        sym = (pd.get("output") or {}).get("symbol")
                except Exception:
                    pass
                if sym:
                    text.append(f"卖出判断 {sym}: {d.get('summary_reason')}")
                    cards.append({"type": "exit_decision", "symbol": sym, **d})
        except Exception:
            pass

        right_panel = {
            "active_run_id": active_run_id,
            "active_symbols": active_symbols,
            "tradeable": tradeable,
            "run_gating": run_gating,
        }

        return {
            "text": "\n".join([t for t in text if t]).strip(),
            "cards": cards,
            "right_panel": right_panel,
        }

    def run_turn(self, session_id: Optional[str], user_message: str) -> Dict[str, Any]:
        sid = store.ensure_session(session_id)
        # Persist user message first
        store.append_message(sid, "user", user_message)

        plan = self._deterministic_plan(user_message)
        tool_results = self._execute_tools(sid, plan)

        # Compose reply surfaces
        composed = self._compose_text(tool_results)

        # Validators
        used_symbols = []
        try:
            rec = next((r for r in tool_results if r.get("tool") == "ensure_recommendation"), None)
            allowed = []
            if rec:
                items = (rec.get("output") or {}).get("items") or []
                allowed = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict) and (it or {}).get("symbol")]
            # explicit symbols from user
            import re
            usersyms = re.findall(r"\b(\d{6})\b", user_message or "")
            SymbolConsistencyValidator(
                final_text=composed.get("text", ""),
                cards=composed.get("cards") or [],
                allowed_symbols=allowed,
                user_explicit_symbols=usersyms,
            )
            TradeabilityConsistencyValidator(
                tradeable=((rec.get("output") or {}).get("tradeable") if rec else None),
                run_gating=((rec.get("output") or {}).get("run_gating") if rec else None),
                final_text=composed.get("text", ""),
                cards=composed.get("cards") or [],
            )
            GroundingRequiredValidator(tool_results=tool_results)
            used_symbols = allowed
        except Exception as e:
            # 不再兜底，直接报错并附带错误码/原因
            composed = {
                "text": f"错误：{str(e) or 'validation_failed'}。",
                "cards": [],
                "right_panel": {},
            }
            tool_results = tool_results or []

        # Persist bundle
        bundle = AssistantBundle.build(
            conversation_id=sid,
            text=composed.get("text") or "",
            cards=composed.get("cards") or [],
            right_panel=composed.get("right_panel") or {},
            tool_calls=plan.get("tools") or [],
            tool_results=tool_results,
            grounding={
                "active_run_id": (next((r.get("output", {}).get("active_run_id") for r in tool_results if r.get("tool") == "ensure_recommendation"), None)),
                "previous_run_id": store.get_state(sid).get("previous_run_id"),
                "focus_symbol": store.get_focus(sid),
                "active_symbols": store.get_state(sid).get("active_symbols") or [],
                "used_symbols": used_symbols,
                "tradeable": (next((r.get("output", {}).get("tradeable") for r in tool_results if r.get("tool") == "ensure_recommendation"), None)),
                "run_gating": (next((r.get("output", {}).get("run_gating") for r in tool_results if r.get("tool") == "ensure_recommendation"), None)),
                "tools_used": [str(t.get("name")) for t in (plan.get("tools") or [])],
            },
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

        # Update session state with latest right panel for quick retrieval
        try:
            store.update_state(sid, {"last_right_panel": payload.get("right_panel")})
        except Exception:
            pass

        return {
            "session_id": sid,
            "reply": composed.get("text") or "",
            "right_panel": payload.get("right_panel") or {},
        }


def run_agent_turn(session_id: Optional[str], user_message: str) -> Dict[str, Any]:
    agent = ToolCallingFinanceAgent()
    return agent.run_turn(session_id, user_message)
