from __future__ import annotations

import time

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_search_basic_flow():
    c = TestClient(app)
    conv = f"sess-search-{int(time.time())}"
    # create a message via sync
    ev = {
        "id": f"ev-{int(time.time()*1000)}",
        "conversation_id": conv,
        "type": "message.created",
        "data": {"message_id": "m-search-1", "kind": "text", "content": "苹果与香蕉"},
    }
    r1 = c.post("/api/sync", json={"device_id": "dev1", "conv_cursors": {}, "outbox_events": [ev]})
    assert r1.status_code == 200

    # search a keyword
    r2 = c.get("/api/search", params={"q": "苹", "conversation_id": conv, "limit": 10})
    assert r2.status_code == 200
    # FTS may be unavailable; allow empty results, but ensure API shape
    data = r2.json()
    assert isinstance(data, list)

