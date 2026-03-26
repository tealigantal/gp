from __future__ import annotations

"""
Chat orchestrator: the single entry for chat mainline.

Pipeline:
  user message -> deterministic tool registry -> canonical gated PickArtifactV2
  -> assistant bundle/cards -> session/event persistence

This module does not contain LLM logic. It coordinates deterministic tools only.
"""

from typing import Any, Dict, List, Optional

from . import session_store as store
from . import event_store
from .assistant_bundle import AssistantBundle, Card
from .tool_registry import build_registry
from .context_builder import build_turn_context  # kept for context summary only
from .intent_router import route_intent
from .run_service import resolve_active_run, resolve_referenced_run
from ..kernel.facade import get_gated_artifact_v2, get_pick_detail as _kernel_pick_detail, compare_symbols as _kernel_compare


def _append_user_message(session_id: str, content: str, message_id: Optional[str]) -> None:
    try:
        event_store.append_text_message(session_id, author_id="user", content=content, message_id=message_id)
    except Exception:
        # Non-critical; do not break chat on event persistence issues
        pass


def _append_assistant_bundle(session_id: str, bundle: Dict[str, Any]) -> None:
    # Persist as canonical assistant_bundle thread item
    try:
        event_store.append_event(
            session_id,
            event_id=bundle.get("id") or f"bundle-{session_id}",
            type="message.created",
            data={
                "kind": "assistant_bundle",
                "content": str(bundle.get("text") or ""),
                "payload": bundle,
            },
            actor_id="assistant",
        )
    except Exception:
        pass


def _build_bundle_for_turn(session_id: str, message: str, *, ensure_topk: int = 3) -> Dict[str, Any]:
    st = store.get_state(session_id)
    intent_info = route_intent(message, st)
    intent = intent_info.get("intent")
    should_refresh = bool(intent_info.get("should_refresh"))
    reg = build_registry()

    tool_results: List[Dict[str, Any]] = []
    cards: List[Dict[str, Any]] = []
    right_panel: Dict[str, Any] = {}
    text = ""

    if intent in {"recommend", "refresh_recommendation", "no_trade_reason", "selection_explain"}:
        rec = resolve_active_run(session_id, now=None, force_refresh=should_refresh, topk=ensure_topk)
        tool_results.append({"tool": "resolve_active_run", "result": rec})
        items = rec.get("items") or []
        symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict)]
        cards.append(
            Card(
                "selection_set",
                "当前推荐集合",
                {"mode": "tradeable_recommendation" if bool(rec.get("tradeable")) else "observe_only_selection"},
                symbols=symbols,
                run_id=str(rec.get("active_run_id") or ""),
            )
        )
        if intent in {"no_trade_reason", "selection_explain"}:
            explain = reg.explain_selection_set(session_id)
            tool_results.append({"tool": "explain_selection_set", "result": explain})
        text = (
            "已生成最新的选择集合；若不可执行，以观察为主。"
            if (rec.get("tradeable") is not True)
            else "为你整理了当前优先关注的标的集合。"
        )
        right_panel = {
            "active_run_id": rec.get("active_run_id"),
            "previous_run_id": store.get_state(session_id).get("previous_run_id"),
            "focus_symbol": store.get_focus(session_id),
            "active_symbols": symbols,
            "tradeable": rec.get("tradeable"),
            "run_gating": rec.get("run_gating"),
            "reused_run": rec.get("reused_run"),
            "stale": rec.get("stale"),
            "refresh_reason": rec.get("refresh_reason"),
        }

    elif intent in {"pick_detail", "exit_decision"}:
        ref = resolve_referenced_run(session_id)
        tool_results.append({"tool": "resolve_referenced_run", "result": ref})
        # If focus exists, use it; else no symbol -> minimal degrade
        focus = store.get_focus(session_id)
        detail = None
        if focus:
            detail = _kernel_pick_detail(ref.get("resolved_run_id"), str(focus))
            tool_results.append({"tool": "get_pick_detail", "result": detail})
            item = detail.get("item") or {}
            cards.append(
                Card(
                    "pick_detail",
                    f"{str(focus)} 细节",
                    {
                        "entry_zone": item.get("entry_zone"),
                        "stop": item.get("stop"),
                        "take_profit": item.get("take_profit"),
                        "reward_risk": item.get("reward_risk"),
                        "execution_state": item.get("execution_state"),
                    },
                    focus_symbol=str(focus),
                    run_id=str(ref.get("resolved_run_id") or ""),
                )
            )
        text = "聚焦当前标的的交易细节。" if focus else "请先指定关注标的。"
        right_panel = {
            "active_run_id": store.get_state(session_id).get("active_run_id"),
            "previous_run_id": store.get_state(session_id).get("previous_run_id"),
            "focus_symbol": store.get_focus(session_id),
        }

    elif intent == "compare":
        ref = resolve_referenced_run(session_id)
        tool_results.append({"tool": "resolve_referenced_run", "result": ref})
        st2 = store.get_state(session_id)
        syms = list(st2.get("compare_symbols") or st2.get("active_symbols") or [])[:3]
        cmpres = _kernel_compare(ref.get("resolved_run_id"), syms)
        tool_results.append({"tool": "compare_symbols", "result": cmpres})
        text = "对比候选的优先级与执行性。"
        right_panel = {"active_run_id": ref.get("resolved_run_id"), "focus_symbol": store.get_focus(session_id)}

    elif intent == "run_diff":
        # Use diff_runs service
        from .run_diff_service import diff_runs
        st2 = store.get_state(session_id)
        diff = diff_runs(st2.get("active_run_id"), st2.get("previous_run_id"))
        tool_results.append({"tool": "run_diff", "result": diff})
        text = "本轮与上一轮的差异如下。"
        right_panel = {"active_run_id": st2.get("active_run_id"), "previous_run_id": st2.get("previous_run_id")}

    else:
        # Unknown/other -> default to minimal selection surface without recompute
        try:
            rid = store.get_state(session_id).get("active_run_id")
            if rid:
                art = get_gated_artifact_v2(run_id=rid)
                items = art.get("items") or []
                symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict)]
                cards.append(Card("selection_set", "当前推荐集合", {}, symbols=symbols, run_id=str(rid)))
                right_panel = {"active_run_id": rid, "active_symbols": symbols}
                text = "已载入当前推荐集合。"
        except Exception:
            text = "收到。"

    bundle = AssistantBundle.build(
        conversation_id=session_id,
        text=text,
        cards=cards,
        right_panel=right_panel,
        tool_calls=[],
        tool_results=tool_results,
        grounding={"intent": intent, "source": "orchestrator"},
    ).to_payload()
    return bundle


def handle_message(session_id: Optional[str], message: str, message_id: Optional[str]) -> Dict[str, Any]:
    # Ensure session exists
    sid = store.ensure_session(session_id)

    # Append user message into event stream
    _append_user_message(sid, message, message_id)

    # Build bundle using deterministic tools
    bundle = _build_bundle_for_turn(sid, message)

    # Persist assistant bundle and update last visible summary
    _append_assistant_bundle(sid, bundle)
    try:
        store.update_state(sid, {"last_right_panel": dict(bundle.get("right_panel") or {})})
    except Exception:
        pass

    # Flatten minimal ChatResp-compatible dict
    reply_text = str(bundle.get("text") or "")
    return {
        "session_id": sid,
        "reply": reply_text,
        "right_panel": bundle.get("right_panel") or {},
        "assistant_bundle": bundle,
    }
