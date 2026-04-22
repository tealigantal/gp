from __future__ import annotations

from typing import Any, Dict

from ..runtime.turn_loop import run_turn_sync
from . import event_store, session_store
from .assistant_bundle import AssistantBundle


def handle_message(session_id: str | None, message: str, _state: Any = None) -> Dict[str, Any]:
    out = run_turn_sync(session_id=session_id, user_message=message)
    sid = out.get("session_id") or session_store.ensure_session(session_id)
    right_panel = out.get("right_panel") or {}
    symbols = right_panel.get("active_symbols") or out.get("symbols") or []
    session_store.update_state(sid, {
        "active_symbols": symbols,
        "active_run_id": right_panel.get("active_run_id") or out.get("run_id"),
    })
    bundle = AssistantBundle.build(
        conversation_id=sid,
        text=out.get("reply") or "",
        cards=[it.get("payload") for it in (out.get("ui_items") or []) if isinstance(it, dict) and it.get("kind") == "card"],
        right_panel=right_panel,
        tool_calls=[],
        tool_results=[],
        grounding={
            "active_run_id": right_panel.get("active_run_id") or out.get("run_id"),
            "active_symbols": symbols,
            "used_symbols": symbols,
            "tradeable": right_panel.get("tradeable"),
            "tools_used": [],
            "run_gating": right_panel.get("run_gating") or {},
        },
    )
    event_store.ensure_conversation(sid, title=sid, conv_type="chat")
    event_store.append_event(
        sid,
        event_id=f"assistant-bundle-{len(event_store.list_events_after(sid, 0, 1000)) + 1}",
        type="message.created",
        data={"message_id": sid, "kind": "assistant_bundle", "content": "", "payload": bundle.to_payload()},
        actor_id="assistant",
    )
    return out
