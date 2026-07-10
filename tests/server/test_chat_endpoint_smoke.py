from __future__ import annotations

import os

from fastapi.testclient import TestClient

os.environ.setdefault("TZ", "Asia/Shanghai")
os.environ.setdefault("STRICT_REAL_DATA", "1")


def test_chat_endpoint_smoke(monkeypatch):
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    def _fake_run_turn_sync(*, session_id: str, user_message: str):
        return {
            "session_id": session_id,
            "reply": f"echo:{user_message}",
            "message": {"message_kind": "chat", "narrative_text": "ok"},
            "run_id": None,
            "symbols": [],
            "right_panel": {},
            "ui_items": [],
            "planner_trace": {},
            "evidence_refs": [],
        }

    monkeypatch.setattr(routes, "run_turn_sync", _fake_run_turn_sync)

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "测试一下"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("session_id")
    assert payload.get("reply") == "echo:测试一下"


def test_chat_endpoint_maps_intent_llm_unavailable(monkeypatch):
    from gp_assistant.core.errors import IntentLLMUnavailable
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    def _fake_run_turn_sync(*, session_id: str, user_message: str):
        raise IntentLLMUnavailable("LLM_API_KEY 未配置")

    monkeypatch.setattr(routes, "run_turn_sync", _fake_run_turn_sync)

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "测试一下"})
    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["error"]["message"] == "LLM 意图解析服务不可用"
    assert payload["error"]["detail"]["reason"] == "LLM_API_KEY 未配置"


def test_chat_endpoint_maps_intent_parse_failed(monkeypatch):
    from gp_assistant.core.errors import IntentParseFailed
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    def _fake_run_turn_sync(*, session_id: str, user_message: str):
        raise IntentParseFailed(
            "LLM intent parser returned invalid JSON after retry",
            reason="JSONDecodeError",
            raw_output="{bad",
            attempts=2,
        )

    monkeypatch.setattr(routes, "run_turn_sync", _fake_run_turn_sync)

    client = TestClient(app)
    response = client.post("/api/chat", json={"message": "测试一下"})
    assert response.status_code == 502, response.text
    payload = response.json()
    assert payload["error"]["message"] == "LLM 意图解析返回无效结果"
    assert payload["error"]["detail"]["attempts"] == 2


def test_chat_endpoint_maps_llm_payload_budget_error(monkeypatch):
    from gp_assistant.core.errors import LLMPayloadBudgetExceeded
    from gp_assistant.gateway.app import app
    from gp_assistant.gateway import routes

    def _fake_run_turn_sync(*, session_id: str, user_message: str):
        raise LLMPayloadBudgetExceeded(
            stage="agent_routing",
            actual_bytes=700_000,
            limit_bytes=600_000,
            budget_report={
                "stage": "agent_routing",
                "total_bytes": 700_000,
                "limit_bytes": 600_000,
                "blocks": [{"name": "messages", "bytes": 690_000, "compressed": True}],
                "context_refs": [{"run_id": "run_1", "symbol": "600001", "rank": 1}],
            },
        )

    monkeypatch.setattr(routes, "run_turn_sync", _fake_run_turn_sync)

    response = TestClient(app).post("/api/chat", json={"message": "测试预算错误"})
    payload = response.json()

    assert response.status_code == 500
    assert payload["error"]["message"] == "LLM 上下文超过预算"
    assert payload["error"]["detail"]["code"] == "llm_payload_budget_exceeded"
    assert payload["error"]["detail"]["stage"] == "agent_routing"
    assert payload["error"]["detail"]["actual_bytes"] == 700_000
