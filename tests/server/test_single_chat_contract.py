from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from gp_assistant.agent_store import AgentStore
from gp_assistant.gateway.app import app
from tests.agent.test_agent_store import make_book, patch_chat_llm


def test_openapi_exposes_product_and_workspace_read_paths():
    paths = TestClient(app).get("/openapi.json").json()["paths"]
    assert {
        "/api/chat",
        "/api/chat/{session_id}",
        "/api/health",
        "/api/book/current",
        "/api/lunch/current",
        "/api/session/{session_id}",
        "/api/session/{session_id}/diagnostics",
        "/api/sessions",
    }.issubset(paths)


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
    response_body = response.json()
    assert response_body["snapshot_id"] == "http-snapshot"
    assert response_body["message"]["narrative_text"] == response_body["reply"]
    replay = client.post("/api/chat", json={"session_id": "s1", "client_turn_id": "c1", "message": "600519 为什么"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["message"]["narrative_text"] == response_body["reply"]
    history = client.get("/api/chat/s1")
    assert history.status_code == 200
    assert [turn["role"] for turn in history.json()["turns"]] == ["user", "assistant"]
    assert history.json()["turns"][-1]["payload"]["message"]["narrative_text"] == response_body["reply"]
    session = client.get("/api/session/s1")
    assert session.status_code == 200
    assert [turn["role"] for turn in session.json()["recent_turns"]] == ["user", "assistant"]
    assert session.json()["recent_turns"][-1]["content"] == response_body["reply"]
    assert session.json()["recent_turns"][-1]["meta"]["message"]["narrative_text"] == response_body["reply"]
    assert client.get("/api/sessions").json()[0]["session_id"] == "s1"


def test_workspace_read_model_allows_a_new_session_without_writing(monkeypatch, tmp_path):
    db = tmp_path / "agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    AgentStore(db).publish_book(make_book("workspace-snapshot"))
    client = TestClient(app)

    book = client.get("/api/book/current")
    assert book.status_code == 200
    assert book.json()["book"]["daybook"]["trading_day"] == "20260713"

    session = client.get("/api/session/not-yet-persisted")
    assert session.status_code == 200
    assert session.json()["session"]["session_id"] == "not-yet-persisted"
    assert session.json()["recent_turns"] == []
    assert client.get("/api/session/not-yet-persisted/diagnostics").status_code == 200


def test_lunch_endpoint_only_declares_the_morning_session_complete(monkeypatch, tmp_path):
    db = tmp_path / "agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    book = make_book("lunch-snapshot").model_copy(
        update={
            "pulse_trade_day": "2026-07-13",
            "pulse_slot_at": "2026-07-13T11:30:00+08:00",
            "slot_status": "OK",
        }
    )
    AgentStore(db).publish_book(book)
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.resolve_daily_target",
        lambda **_: SimpleNamespace(
            market_phase="LUNCH_BREAK",
            pulse_trade_day="2026-07-13",
            pulse_slot_closed_at="2026-07-13T11:30:00+08:00",
            decision_trade_day="2026-07-13",
            daybook_effective_day="2026-07-10",
            target_mode="previous_completed",
        ),
    )

    response = TestClient(app).get("/api/lunch/current")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "READY"
    assert payload["session"] == {
        "name": "morning_session",
        "target_closed_at": "2026-07-13T11:30:00+08:00",
        "completed_at": "2026-07-13T11:30:00+08:00",
        "complete": True,
    }
    assert payload["daily"]["today_complete"] is False


def test_no_legacy_endpoint_is_available():
    client = TestClient(app)
    for path in ("/api/recommend_v2", "/api/workbench", "/health"):
        assert client.get(path).status_code == 404
