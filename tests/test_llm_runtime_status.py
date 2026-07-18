from __future__ import annotations

import gp_assistant.llm.client as client_module


def test_committed_product_chat_health_is_shared_through_store(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(
        client_module.LLMClient,
        "available",
        lambda _self: (True, "ok"),
    )
    monkeypatch.setattr(
        client_module,
        "_RUNTIME_STATUS",
        {key: None for key in client_module._RUNTIME_STATUS},
    )
    trace = [
        {
            "stage": "intent_routing",
            "success": True,
            "http_status": 200,
            "request_model": "test-model",
            "response_model": "test-model",
            "response_id": "routing-response",
        },
        {
            "stage": "tool_evidence",
            "success": True,
            "http_status": 200,
            "request_model": "test-model",
            "response_model": "test-model",
            "response_id": "narration-response",
        },
    ]

    client_module.record_product_chat(success=True, stage="committed", trace=trace)
    # Simulate a different Uvicorn worker with no in-memory request history.
    client_module._RUNTIME_STATUS = {
        key: None for key in client_module._RUNTIME_STATUS
    }

    status = client_module.llm_status()

    assert status["verification"] == "ready"
    assert status["product_chat_last_success"] is True
    assert status["product_chat_last_stage"] == "committed"
    assert (tmp_path / "store" / "llm_runtime_status.json").exists()


def test_failed_product_chat_keeps_a_configured_llm_retryable(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setattr(
        client_module.LLMClient,
        "available",
        lambda _self: (True, "ok"),
    )
    monkeypatch.setattr(
        client_module,
        "_RUNTIME_STATUS",
        {key: None for key in client_module._RUNTIME_STATUS},
    )

    client_module.record_product_chat(
        success=False,
        stage="grounding_repair",
        error=RuntimeError("llm_narration_misbound_take1_numeric:0.73"),
    )

    status = client_module.llm_status()

    assert status["verification"] == "error"
    assert status["configured"] is True
