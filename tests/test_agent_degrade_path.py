from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_llm_unavailable_degrades_with_deterministic_reply():
    c = TestClient(app)
    # Ensure have a recommend context
    r1 = c.post("/api/chat", json={"message": "服务荐股"})
    sid = r1.json()["session_id"]
    # Ask for analysis which should not depend on LLM
    r2 = c.post("/api/chat", json={"session_id": sid, "message": "看下K线和买卖点"})
    j2 = r2.json()
    # Degraded allowed; reply should contain structured hints
    assert j2["reply"], "reply should not be empty"
    # Best-effort checks for deterministic content
    assert ("S1=" in j2["reply"]) or ("关键带" in j2["reply"]) or ("标的：" in j2["reply"]) 
