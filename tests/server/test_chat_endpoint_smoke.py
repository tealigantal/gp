from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_chat_endpoint_smoke(monkeypatch):
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    def _fake_run_turn_sync(*, session_id: str, user_message: str):
        return {
            "session_id": session_id,
            "reply": f"echo:{user_message}",
            "message": {"message_kind": "chat", "narrative_text": "ok"},
            "run_id": None,
            "symbols": [],
            "right_panel": {},
            "ui_items": [],
            "planner_trace": {},
            "evidence_refs": [],
        }

    monkeypatch.setattr(routes, "run_turn_sync", _fake_run_turn_sync)

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "测试一下"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("session_id")
    assert payload.get("reply") == "echo:测试一下"
