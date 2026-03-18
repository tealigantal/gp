from __future__ import annotations

from fastapi.testclient import TestClient
from gp_assistant.server.app import app


def test_exit_decision_basic_path():
    c = TestClient(app)
    r = c.post('/api/chat', json={'message': '600519 现在该不该卖'})
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j.get('reply'), str)
    assert '建议' in j.get('reply')

