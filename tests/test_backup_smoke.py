from __future__ import annotations

import time

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_export_import_roundtrip():
    c = TestClient(app)
    conv = f"sess-bak-{int(time.time())}"
    ev = {
        "id": f"ev-{int(time.time()*1000)}",
        "conversation_id": conv,
        "type": "message.created",
        "data": {"message_id": "m-bak-1", "kind": "text", "content": "backup"},
    }
    r1 = c.post("/api/sync", json={"device_id": "dev1", "conv_cursors": {}, "outbox_events": [ev]})
    assert r1.status_code == 200

    r2 = c.get(f"/api/conversations/{conv}/export")
    assert r2.status_code == 200
    data = r2.json()
    assert data.get("conversation", {}).get("id") == conv
    assert len(data.get("events", [])) >= 1

    # import back should not error (idempotent-ish)
    r3 = c.post("/api/conversations/import", json=data)
    assert r3.status_code == 200
    assert r3.json().get("status") == "ok"

