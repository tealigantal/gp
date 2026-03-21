from __future__ import annotations

import os
from typing import Any, Dict

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def test_ready_with_external_llm_skips_probe(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com/beta")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    client = TestClient(app)

    # Ready endpoint
    r = client.get("/api/health/ready")
    assert r.status_code == 200, r.text
    data: Dict[str, Any] = r.json()
    assert data.get("ok") is True
    checks = data.get("checks") or {}
    assert "llm" in checks and "llm_proxy" not in checks
    assert (checks.get("llm") or {}).get("skipped") is True

    # Light health should report ok and llm_ready True
    r2 = client.get("/api/health")
    assert r2.status_code == 200, r2.text
    d2 = r2.json()
    assert d2.get("status") == "ok"
    assert d2.get("llm_ready") is True

