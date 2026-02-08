from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_chat_multiturn_smoke():
    c = TestClient(app)
    # 1) casual chat
    r1 = c.post("/chat", json={"message": "你好"})
    j1 = r1.json()
    sid = j1["session_id"]
    assert j1["reply"]
    # 2) trigger recommend
    r2 = c.post("/chat", json={"session_id": sid, "message": "给我推荐3只主板低吸"})
    j2 = r2.json()
    assert j2["tool_trace"]["triggered_recommend"] is True
    # 3) follow-up why/stop loss
    r3 = c.post("/chat", json={"session_id": sid, "message": "为什么选它？止损怎么定？"})
    j3 = r3.json()
    assert j3["reply"]

