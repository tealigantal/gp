import os
from typing import Any, Dict

from fastapi.testclient import TestClient

os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from gp_assistant.gateway.app import app  # noqa: E402


client = TestClient(app)


def test_health_api_and_legacy():
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    data = response.json()
    for key in ["status", "llm_ready", "storage", "trading_day"]:
        assert key in data

    legacy = client.get("/health")
    assert legacy.status_code == 200


def test_openapi_current_paths_present():
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths: Dict[str, Any] = response.json().get("paths", {})
    for path in ["/api/health", "/api/chat", "/api/book/current", "/api/session/{session_id}", "/api/sessions"]:
        assert path in paths


def test_book_current_no_500():
    response = client.get("/api/book/current")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "book" in data and isinstance(data["book"], dict)
    assert "book_version" in data["book"]


def test_sessions_endpoint_shape():
    response = client.get("/api/sessions")
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data, list)
    if data:
        item = data[0]
        for key in ["session_id", "created_at", "updated_at", "title", "preview"]:
            assert key in item
