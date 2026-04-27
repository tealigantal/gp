import os

from fastapi.testclient import TestClient

os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from gp_assistant.gateway.app import app  # noqa: E402
from gp_assistant.gateway import routes  # noqa: E402


client = TestClient(app)


class _Book:
    book_version = "book_1"
    artifact_id = "artifact_1"
    updated_at = "2026-01-01T15:01:00"
    daybook_effective_day = "20260101"
    pulse_trade_day = "20260101"
    pulse_slot_at = "2026-01-01 14:55:00"
    last_closed_5m = "2026-01-01 14:55:00"
    slot_status = "DEGRADED"
    publish_allowed = False
    board = []
    daybook = type("Daybook", (), {"picks": [], "reserve_picks": [], "reserve_symbols": []})()
    tracked_universe = type("Tracked", (), {"total": []})()


def test_health_includes_runtime_tools():
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    data = response.json()
    runtime = data.get("runtime", {})
    assert runtime.get("auto_update_service") == "gp-worker"
    assert "book_freshness" in runtime
    assert "daily_freshness_ready" in runtime
    services = runtime.get("services", [])
    service_names = {item.get("service") for item in services}
    assert {"gp", "gp-worker", "gp-rebuild-daybook", "gp-replay-today", "gp-postclose-archive"} <= service_names


def test_ops_endpoint_runs_rebuild_daybook(monkeypatch):
    monkeypatch.setattr(routes, "reconcile_runtime_state", lambda operation="auto": {"trade_day": "20260101", "artifact_id": "slot_init", "operation": operation})
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(routes, "audit_daily_freshness", lambda **_: {"target_day": "2026-01-01", "focus_symbols": [], "focus_stale_symbols": []})
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: {})
    response = client.post("/api/ops/gp-rebuild-daybook/run")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["operation"] == "gp-rebuild-daybook"
    assert data["status"] == "ok"
    assert data["result"]["artifact_id"] == "slot_init"
    assert data["result"]["operation"] == "rebuild_daybook"
    assert data["runtime"]["artifact_id"] == "artifact_1"


def test_ops_endpoint_rejects_unknown_service():
    response = client.post("/api/ops/not-real/run")
    assert response.status_code == 404, response.text


def test_daily_freshness_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(
        routes,
        "audit_daily_freshness",
        lambda **_: {"target_day": "2026-01-01", "focus_symbols": ["002371"], "focus_stale_symbols": ["002371"]},
    )
    response = client.get("/api/health/daily-freshness")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["focus_stale_symbols"] == ["002371"]
