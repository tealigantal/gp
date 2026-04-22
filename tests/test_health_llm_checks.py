from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.gateway.app import app
from gp_assistant.gateway import routes


def test_health_reports_llm_ready_when_client_available(monkeypatch):
    class DummyLLM:
        def available(self):
            return True, "ok"

    monkeypatch.setattr(routes, "LLMClient", lambda: DummyLLM())
    client = TestClient(app)

    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("status") == "ok"
    assert data.get("llm_ready") is True
    assert "storage" in data
