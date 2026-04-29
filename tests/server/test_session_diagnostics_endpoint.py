from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_session_diagnostics_endpoint_returns_safe_summary(monkeypatch):
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    monkeypatch.setattr(
        routes,
        "get_session_diagnostics",
        lambda session_id: {
            "session_id": session_id,
            "focus": {
                "active_run_id": "run_1",
                "previous_run_id": "run_0",
                "last_focus_symbol": "600111",
                "last_focus_rank": 1,
                "compare_set": ["600111", "603993"],
            },
            "latest_assistant": {
                "turn_id": "t1",
                "seq": 2,
                "message_kind": "live_entry_check",
                "narrative_text": "当前只适合观察，不建议直接进。",
                "symbol": "600111",
                "run_action": "NO_TRADE",
                "followup_suggestions": ["这只现在还能买吗"],
            },
            "assistant_messages": [],
        },
    )

    client = TestClient(app)
    response = client.get("/api/session/test-session/diagnostics")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session_id"] == "test-session"
    assert payload["focus"]["last_focus_symbol"] == "600111"
    assert payload["latest_assistant"]["message_kind"] == "live_entry_check"
    assert "tool_trace" not in str(payload)
