from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.agent_store import AgentStore
from gp_assistant.gateway.app import app
from tests.agent.test_agent_store import make_book, patch_chat_llm


def test_openapi_exposes_only_product_api_paths():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert set(paths) == {"/api/chat", "/api/chat/{session_id}", "/api/health"}


def test_chat_requires_client_turn_id():
    response = TestClient(app).post("/api/chat", json={"message": "推荐"})
    assert response.status_code == 422


def test_http_chat_and_history_bind_one_published_snapshot(monkeypatch, tmp_path):
    patch_chat_llm(monkeypatch)
    db = tmp_path / "agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    AgentStore(db).publish_book(make_book("http-snapshot"))
    client = TestClient(app)
    response = client.post("/api/chat", json={"session_id": "s1", "client_turn_id": "c1", "message": "600519 为什么"})
    assert response.status_code == 200, response.text
    assert response.json()["snapshot_id"] == "http-snapshot"
    history = client.get("/api/chat/s1")
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()["turns"]] == ["user", "assistant"]


def test_no_legacy_endpoint_is_available():
    client = TestClient(app)
    for path in ("/api/book/current", "/api/recommend_v2", "/api/workbench", "/api/sessions", "/health"):
        assert client.get(path).status_code == 404
