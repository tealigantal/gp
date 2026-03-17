from __future__ import annotations

from fastapi.testclient import TestClient
from gp_assistant.server.app import app


def test_validation_endpoints_smoke():
    c = TestClient(app)
    r1 = c.get('/api/validation/strategy/S1')
    assert r1.status_code == 200
    j1 = r1.json()
    assert 'strategy' in j1 and 'event_stats' in j1
    r2 = c.get('/api/paperfolio')
    assert r2.status_code == 200
    j2 = r2.json()
    assert 'picks' in j2
