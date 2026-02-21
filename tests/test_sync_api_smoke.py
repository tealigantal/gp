from __future__ import annotations

import time

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_sync_append_and_delta():
    c = TestClient(app)
    conv = f"sess-sync-{int(time.time())}"
    # 1) push an event (message.created)
    ev = {
        "id": f"ev-{int(time.time()*1000)}",
        "conversation_id": conv,
        "type": "message.created",
        "data": {"message_id": "m-1", "kind": "text", "content": "hello sync"},
    }
    r1 = c.post("/api/sync", json={"device_id": "dev1", "conv_cursors": {}, "outbox_events": [ev]})
    assert r1.status_code == 200, r1.text
    j1 = r1.json()
    assert j1["ack"].get(ev["id"]).startswith("accepted:"), j1

    # 2) pull delta after 0
    r2 = c.post(
        "/api/sync",
        json={"device_id": "dev1", "conv_cursors": {conv: 0}, "outbox_events": []},
    )
    assert r2.status_code == 200
    j2 = r2.json()
    assert conv in j2["deltas"]
    events = j2["deltas"][conv]
    assert len(events) >= 1
    assert events[0]["type"] == "message.created"
    assert events[0]["data"]["content"] == "hello sync"

