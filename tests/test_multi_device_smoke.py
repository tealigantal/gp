from __future__ import annotations

import time

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_idempotent_event_append():
    c = TestClient(app)
    conv = f"sess-md-{int(time.time())}"
    eid = f"ev-md-{int(time.time()*1000)}"
    ev = {
        "id": eid,
        "conversation_id": conv,
        "type": "message.created",
        "data": {"message_id": f"m-{eid}", "kind": "text", "content": "md-1"},
    }
    r1 = c.post("/api/sync", json={"device_id": "devA", "conv_cursors": {}, "outbox_events": [ev]})
    assert r1.status_code == 200
    ack1 = r1.json()["ack"][eid]
    assert ack1.startswith("accepted:")
    r2 = c.post("/api/sync", json={"device_id": "devB", "conv_cursors": {}, "outbox_events": [ev]})
    assert r2.status_code == 200
    ack2 = r2.json()["ack"][eid]
    assert ack2.startswith("accepted:")
    # both should refer to the same seq
    s1 = int(ack1.split(":", 1)[1])
    s2 = int(ack2.split(":", 1)[1])
    assert s1 == s2

