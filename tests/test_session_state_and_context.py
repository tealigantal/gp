import os
os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from typing import Any, Dict

from gp_assistant.chat_compat import session_store as store
from gp_assistant.chat_compat import event_store
from gp_assistant.chat_compat.assistant_bundle import AssistantBundle
from gp_assistant.chat_compat.context_builder import build_turn_context


def test_session_state_persists_extended_fields(tmp_path):
    sid = store.ensure_session(None)

    # Update newly added fields and verify persistence
    rp = {"active_run_id": "run-x", "active_symbols": ["600150", "601288"], "tradeable": True}
    updates: Dict[str, Any] = {
        "last_right_panel": rp,
        "pending_action": "explain",
        "pending_symbols": ["600150"],
        "pending_cursor": 0,
        "last_reference_resolution": {"resolution_type": "ordinal", "ordinal": 2, "symbol": "601288"},
        "last_surface_kind": "assistant_bundle",
        "last_tool_results_summary": {"tools_used": ["ensure_recommendation"], "used_symbols": ["600150", "601288"], "active_run_id": "run-x", "tradeable": True},
        "last_visible_assistant_summary": {"text_head": "ok", "card_types": ["recommendation"], "active_run_id": "run-x"},
    }
    store.update_state(sid, updates)
    st = store.get_state(sid)
    assert st.get("last_right_panel", {}) == rp
    assert st.get("pending_action") == "explain"
    assert st.get("pending_symbols") == ["600150"]
    assert st.get("pending_cursor") == 0
    assert isinstance(st.get("last_tool_results_summary"), dict)
    assert isinstance(st.get("last_visible_assistant_summary"), dict)


def test_build_turn_context_layers_with_assistant_bundle():
    sid = store.ensure_session(None)
    # Ensure event store conversation exists
    event_store.ensure_conversation(sid, title=sid, conv_type="chat")
    event_store.ensure_participant(sid)

    # Append a user text via session_store (also mirrors to event_store)
    store.append_message(sid, "user", "閻㈢喐鍨氶幒銊ㄥ礃")

    # Build and append a minimal assistant bundle event
    bundle = AssistantBundle.build(
        conversation_id=sid,
        text="娑撳褰ч崐娆撯偓澶婎洤娑?,
        cards=[{"type": "recommendation", "items": [{"symbol": "600150"}, {"symbol": "601288"}, {"symbol": "002371"}]}],
        right_panel={
            "active_run_id": "run-abc",
            "active_symbols": ["600150", "601288", "002371"],
            "tradeable": True,
            "run_gating": {"decision": "allow"},
        },
        tool_calls=[{"tool": "ensure_recommendation", "args": {}}],
        tool_results=[{"tool": "ensure_recommendation", "output": {"active_run_id": "run-abc", "items": [{"symbol": "600150"}, {"symbol": "601288"}, {"symbol": "002371"}], "tradeable": True}}],
        grounding={
            "source": "test",
            "active_run_id": "run-abc",
            "active_symbols": ["600150", "601288", "002371"],
            "used_symbols": ["600150", "601288", "002371"],
            "tools_used": ["ensure_recommendation"],
            "tradeable": True,
        },
    )
    payload = bundle.to_payload()
    ev_id = f"ab-{sid}-test"
    event_store.append_event(
        sid,
        event_id=ev_id,
        type="message.created",
        data={"message_id": ev_id, "kind": "assistant_bundle", "content": "", "payload": payload},
        actor_id="assistant",
    )

    # Build turn context
    ctx = build_turn_context(sid)
    # Check layered keys
    assert "session_state" in ctx
    assert "active_artifact_summary" in ctx
    assert "recent_dialogue" in ctx
    assert "recent_tool_trace_summary" in ctx
    assert "continuation_state" in ctx

    # recent_dialogue should include assistant_bundle item with card_types
    rd = ctx.get("recent_dialogue") or []
    assert any((d.get("role") == "assistant" and d.get("kind") == "assistant_bundle") for d in rd)

    # recent_tool_trace_summary should reflect tools_used
    rts = ctx.get("recent_tool_trace_summary") or []
    if rts:
        s = rts[-1]
        assert "tools_used" in s
        assert "active_run_id" in s
