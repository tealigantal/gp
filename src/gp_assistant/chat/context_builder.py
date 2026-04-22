from __future__ import annotations

from typing import Any, Dict, List

from . import event_store, session_store


def build_turn_context(session_id: str) -> Dict[str, Any]:
    state = session_store.get_state(session_id)
    events = event_store.list_events_after(session_id, 0, limit=50)
    recent_dialogue: List[Dict[str, Any]] = []
    recent_tool_trace_summary: List[Dict[str, Any]] = []
    active_artifact_summary: Dict[str, Any] = {}
    for event in events:
        data = event.get("data") or {}
        if data.get("kind") == "assistant_bundle":
            payload = data.get("payload") or {}
            recent_dialogue.append({"role": "assistant", "kind": "assistant_bundle", "card_types": [c.get("type") for c in (payload.get("cards") or [])]})
            grounding = payload.get("grounding") or {}
            recent_tool_trace_summary.append({
                "tools_used": grounding.get("tools_used") or [t.get("tool") for t in (payload.get("tool_results") or []) if isinstance(t, dict)],
                "active_run_id": grounding.get("active_run_id"),
            })
            active_artifact_summary = {
                "active_run_id": grounding.get("active_run_id"),
                "active_symbols": grounding.get("active_symbols") or [],
                "tradeable": grounding.get("tradeable"),
            }
    return {
        "session_state": state,
        "active_artifact_summary": active_artifact_summary,
        "recent_dialogue": recent_dialogue,
        "recent_tool_trace_summary": recent_tool_trace_summary,
        "continuation_state": {
            "focus_symbol": state.get("focused_symbol") or state.get("last_focus_symbol"),
            "referenced_run_id": state.get("referenced_run_id"),
        },
    }
