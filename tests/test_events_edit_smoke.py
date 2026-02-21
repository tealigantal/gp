from __future__ import annotations

import time

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_event_edit_flow():
    c = TestClient(app)
    conv = f"sess-edit-{int(time.time())}"
    mid = f"m-edit-{int(time.time()*1000)}"
    # create
    ev1 = {
        "id": f"ev-{mid}",
        "conversation_id": conv,
        "type": "message.created",
        "data": {"message_id": mid, "kind": "text", "content": "first"},
    }
    # edit
    ev2 = {
        "id": f"ev2-{mid}",
        "conversation_id": conv,
        "type": "message.edited",
        "data": {"message_id": mid, "content": "second"},
    }
    r = c.post("/api/sync", json={"device_id": "dev1", "conv_cursors": {}, "outbox_events": [ev1, ev2]})
    assert r.status_code == 200
    # read back events after 0
    rr = c.get(f"/api/conversations/{conv}/events", params={"after": 0, "limit": 10})
    assert rr.status_code == 200
    evs = rr.json()
    types = [e["type"] for e in evs]
    assert "message.created" in types and "message.edited" in types

