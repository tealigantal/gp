from __future__ import annotations

import os
from fastapi.testclient import TestClient

os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_chat_endpoint_smoke():
    from gp_assistant.server.app import app

    client = TestClient(app)
    r = client.post("/api/chat", json={"message": "测试一下"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("session_id")
    assert isinstance(j.get("reply"), str)

