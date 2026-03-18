from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def _runid(resp_json):
    ctx = resp_json.get("followup_context") or {}
    return ctx.get("active_run_id") or resp_json.get("run_id")


def test_followup_uses_same_run_and_refresh_new_run():
    c = TestClient(app)
    # 1) initial recommend via chat
    r1 = c.post("/api/chat", json={"message": "latest recommend 3"})
    assert r1.status_code == 200
    j1 = r1.json()
    rid1 = _runid(j1)
    assert rid1, "run_id must be set after recommend"

    # 2) ordinal (second) should work and keep same run
    r2 = c.post("/api/chat", json={"session_id": j1["session_id"], "message": "第二只"})
    j2 = r2.json()
    rid2 = _runid(j2)
    assert rid2 == rid1
    assert j2.get("reply"), "should reply"

    # 3) no-trade explain should read run gating (ok even if tradeable)
    r3 = c.post("/api/chat", json={"session_id": j1["session_id"], "message": "为什么空仓"})
    j3 = r3.json()
    assert _runid(j3) == rid1
    assert isinstance(j3.get("reply"), str)

    # 4) refresh -> new run_id and a new card
    r4 = c.post("/api/chat", json={"session_id": j1["session_id"], "message": "重新算"})
    j4 = r4.json()
    rid4 = _runid(j4)
    assert rid4 and rid4 != rid1
    assert "新" in j4.get("reply", "") or j4.get("reply"), "reply indicates refresh"

