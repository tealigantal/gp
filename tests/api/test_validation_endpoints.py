from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app


def test_gateway_auxiliary_endpoints_smoke():
    client = TestClient(app)

    side_results = client.get('/api/side-results')
    assert side_results.status_code == 200
    assert isinstance(side_results.json(), list)

    sessions = client.get('/api/sessions')
    assert sessions.status_code == 200
    assert isinstance(sessions.json(), list)
