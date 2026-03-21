from __future__ import annotations

from fastapi.testclient import TestClient
from gp_assistant.server.app import app


def test_recommend_v2_endpoint_import_and_call():
    client = TestClient(app)
    r = client.get('/api/recommend_v2')
    assert r.status_code in (200, 404)
    data = r.json()
    # When artifact not found, our sanitized response has ok=false; otherwise expect artifact_version=v2
    if isinstance(data, dict) and data.get('error') == 'recommend_v2_unavailable':
        # accept sanitized error shape
        assert data.get('artifact_version') == 'v2'
    else:
        assert data.get('artifact_version') == 'v2'
