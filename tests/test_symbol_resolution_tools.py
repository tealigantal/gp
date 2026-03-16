from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.server.app import app
from gp_assistant.chat import session_store as store


def _start_session_with_picks(client: TestClient) -> str:
    r = client.post("/api/chat", json={"message": "latest recommend"})
    sid = r.json()["session_id"]
    # Seed symbols to avoid dependency on data files
    store.update_state(sid, {"last_recommend_symbols": ["600519", "000333", "000001"]})
    return sid


def test_resolve_code_and_ordinals_and_pronoun():
    c = TestClient(app)
    sid = _start_session_with_picks(c)

    # code direct
    r1 = c.post("/api/chat", json={"session_id": sid, "message": "研究K线 600519"})
    j1 = r1.json()
    assert j1.get("reply")

    # ordinal: second
    r2 = c.post("/api/chat", json={"session_id": sid, "message": "第二只"})
    j2 = r2.json()
    assert j2.get("resolved_symbol") in {"000333", "600519", "000001"}

    # pronoun: 这只 → use focus
    r3 = c.post("/api/chat", json={"session_id": sid, "message": "这只 K线"})
    j3 = r3.json()
    assert j3.get("reply")

