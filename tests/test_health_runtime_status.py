import os
from types import SimpleNamespace

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
    tracked_universe = type("Tracked", (), {"total": []})()
    daybook = type(
        "Daybook",
        (),
        {
            "picks": [],
            "reserve_picks": [],
            "reserve_symbols": [],
            "source_meta": {
                "daily_freshness": {
                    "ready": False,
                    "target_day": "2026-01-01",
                    "checked_symbols": ["002371", "002716"],
                    "checked_count": 2,
                    "stale_symbols": ["002371"],
                    "stale_count": 1,
                    "failed_symbols": ["002716"],
                    "blocking_reason": "daily freshness blocked",
                    "last_reconcile_at": "2026-01-01T15:00:00",
                }
            },
        },
    )()


def _config(intraday_runtime_enabled: bool = True):
    return SimpleNamespace(
        provider=SimpleNamespace(data_provider="akshare"),
        intraday_runtime_enabled=intraday_runtime_enabled,
        intraday_poll_interval_sec=15,
    )


def test_health_includes_runtime_tools(monkeypatch):
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    runtime = response.json().get("runtime", {})
    assert runtime.get("auto_update_service") == "gp-worker"
    assert runtime.get("book_freshness") == "degraded"
    assert runtime.get("daily_freshness_ready") is False
    assert runtime.get("daily_checked_count") == 2
    assert runtime.get("daily_stale_count") == 1
    assert runtime.get("daily_failed_symbols") == ["002716"]
    services = runtime.get("services", [])
    service_names = {item.get("service") for item in services}
    assert {"gp", "gp-worker", "gp-rebuild-daybook", "gp-replay-today", "gp-postclose-archive"} <= service_names


def test_health_reports_intraday_runtime_disabled(monkeypatch):
    monkeypatch.setattr(routes, "load_config", lambda: _config(False))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    runtime = response.json().get("runtime", {})
    assert runtime.get("intraday_runtime_enabled") is False
    assert runtime.get("book_freshness") == "daily_only"
    assert "5" in str(runtime.get("blocking_reason") or "")


def test_ops_endpoint_runs_rebuild_daybook(monkeypatch):
    monkeypatch.setattr(
        routes,
        "reconcile_runtime_state",
        lambda operation="auto": {"trade_day": "20260101", "artifact_id": "slot_init", "operation": operation},
    )
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    response = client.post("/api/ops/repair/gp-rebuild-daybook")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["operation"] == "gp-rebuild-daybook"
    assert data["status"] == "ok"
    assert data["result"]["artifact_id"] == "slot_init"
    assert data["result"]["operation"] == "rebuild_daybook"
    assert data["runtime"]["artifact_id"] == "artifact_1"


def test_ops_endpoint_rejects_unknown_service():
    response = client.post("/api/ops/repair/not-real")
    assert response.status_code == 404, response.text


def test_repair_status_returns_runtime_snapshot(monkeypatch):
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    response = client.get("/api/ops/repair/status")
    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["artifact_id"] == "artifact_1"
    assert runtime["daily_checked_count"] == 2
    assert runtime["daily_failed_symbols"] == ["002716"]
