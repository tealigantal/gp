from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app
from gp_assistant.gateway import routes


def test_health_includes_storage_stats(monkeypatch):
    client = TestClient(app)

    monkeypatch.setattr(routes, 'load_current_book', lambda: None)
    monkeypatch.setattr(routes, 'current_trading_day', lambda: '2026-04-21')
    monkeypatch.setattr(routes, 'gateway_stats', lambda: {
        'session_count': 3,
        'transcript_count': 12,
        'claim_count': 5,
        'latest_session_at': '2026-04-21T10:30:00+08:00',
    })
    monkeypatch.setattr(routes.LLMClient, 'available', lambda self: (True, None))

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['trading_day'] == '2026-04-21'
    assert payload['llm_ready'] is True
    assert payload['storage'] == {
        'session_count': 3,
        'transcript_count': 12,
        'claim_count': 5,
        'latest_session_at': '2026-04-21T10:30:00+08:00',
    }
