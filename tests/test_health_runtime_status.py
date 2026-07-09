import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from gp_assistant.gateway.app import app  # noqa: E402
from gp_assistant.gateway import routes  # noqa: E402


client = TestClient(app)


@pytest.fixture(autouse=True)
def _stable_daily_target(monkeypatch):
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-01-01",
            "target_mode": "current_pending",
            "pending_eod_day": "2026-01-01",
            "eod_probe": {"ready": False, "ok_count": 1, "next_retry_after": "2026-01-01T15:05:00+08:00"},
        },
    )
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: None)


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
                    "target_mode": "current_pending",
                    "pending_eod_day": "2026-01-01",
                    "eod_probe": {"ready": False, "ok_count": 1, "next_retry_after": "2026-01-01T15:05:00+08:00"},
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


class _ReadyBook:
    book_version = "daily_old"
    artifact_id = "daily_old"
    trading_day = "20260512"
    updated_at = "2026-05-12T10:42:54+08:00"
    daybook_effective_day = "20260512"
    pulse_trade_day = None
    pulse_slot_at = None
    last_closed_5m = None
    slot_status = "OK"
    publish_allowed = True
    board = []
    tracked_universe = type("Tracked", (), {"total": []})()
    daybook = type(
        "Daybook",
        (),
        {
            "generated_at": "2026-05-12T16:52:00+08:00",
            "source_meta": {
                "daily_freshness": {
                    "ready": True,
                    "target_day": "2026-05-12",
                    "target_mode": "current_ready",
                    "checked_count": 50,
                    "stale_count": 0,
                    "last_reconcile_at": "2026-05-12T16:52:00+08:00",
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
    assert runtime.get("intraday_runtime_enabled") is True
    assert runtime.get("book_freshness") == "eod_pending"
    assert runtime.get("daily_status") == "eod_pending"
    assert runtime.get("daily_freshness_ready") is False
    assert runtime.get("daily_target_mode") == "current_pending"
    assert runtime.get("pending_eod_day") == "2026-01-01"
    assert runtime.get("eod_probe", {}).get("ok_count") == 1
    assert runtime.get("daily_checked_count") == 2
    assert runtime.get("daily_stale_count") == 1
    assert runtime.get("daily_failed_symbols") == ["002716"]
    services = runtime.get("services", [])
    service_names = {item.get("service") for item in services}
    assert {"gp", "gp-worker", "gp-rebuild-daybook", "gp-postclose-archive"} <= service_names
    assert "gp-replay-today" not in service_names


def test_health_reports_intraday_runtime_disabled(monkeypatch):
    monkeypatch.setattr(routes, "load_config", lambda: _config(False))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    runtime = response.json().get("runtime", {})
    assert runtime.get("intraday_runtime_enabled") is False
    assert runtime.get("book_freshness") == "eod_pending"
    assert "日线计划" in str(runtime.get("blocking_reason") or "")


def test_health_reports_daily_blocked_when_postclose_current_ready_but_freshness_missing(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260101",
        target_pulse_trade_day="20260101",
        target_pulse_slot_at="2026-01-01 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20250101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260102",
    )
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-01-01",
            "target_mode": "current_ready",
            "pending_eod_day": None,
            "eod_probe": {"ready": True, "ok_count": 3},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json().get("runtime", {})
    assert runtime.get("book_freshness") == "freshness_blocked"
    assert runtime.get("daily_status") == "freshness_blocked"


def test_health_reports_daily_reconciling_after_eod_ready_before_report(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260709",
        target_pulse_trade_day="20260709",
        target_pulse_slot_at="2026-07-09 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20250101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260710",
    )
    book = SimpleNamespace(
        book_version="slot_20260709",
        artifact_id="slot_20260709",
        trading_day="20260709",
        updated_at="2026-07-09T14:57:28+08:00",
        daybook_effective_day="20260709",
        pulse_trade_day="20260709",
        pulse_slot_at="2026-07-09 14:55:00",
        last_closed_5m="2026-07-09 14:55:00",
        slot_status="OK",
        publish_allowed=False,
        board=[],
        tracked_universe=SimpleNamespace(total=[]),
        daybook=SimpleNamespace(
            generated_at="2026-07-09T00:59:06+08:00",
            source_meta={
                "daily_freshness": {
                    "ready": True,
                    "target_day": "2026-07-08",
                    "target_mode": "previous_completed",
                    "checked_count": 30,
                    "stale_count": 0,
                }
            },
        ),
    )
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: book)
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: None)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-07-09",
            "target_mode": "current_ready",
            "pending_eod_day": None,
            "eod_probe": {"ready": True, "ok_count": 3},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json().get("runtime", {})
    assert runtime.get("daily_status") == "daily_reconciling"
    assert runtime.get("book_freshness") == "daily_reconciling"
    assert runtime.get("daily_target_day") == "2026-07-09"
    assert runtime.get("daily_target_mode") == "current_ready"
    assert runtime.get("daily_checked_count") == 0


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


def test_runtime_daily_target_prefers_resolver_over_stale_book(monkeypatch):
    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-04-29",
            "target_mode": "previous_completed",
            "pending_eod_day": None,
            "eod_probe": None,
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["daily_target_day"] == "2026-04-29"
    assert runtime["daily_target_mode"] == "previous_completed"
    assert runtime["pending_eod_day"] is None
    assert runtime["eod_probe"] is None
    assert runtime["daily_checked_count"] == 0
    assert runtime["daily_stale_count"] == 0
    assert runtime["daily_blocking_reason"] is None
    assert runtime["daily_failed_symbols"] == []


def test_health_preserves_postclose_current_pending_when_latest_report_is_previous_completed(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260709",
        target_pulse_trade_day="20260709",
        target_pulse_slot_at="2026-07-09 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20250101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260710",
    )
    latest_previous_report = {
        "ready": True,
        "target_day": "2026-07-08",
        "target_mode": "previous_completed",
        "checked_count": 30,
        "stale_count": 0,
        "stale_symbols": [],
        "failed_symbols": [],
        "blocking_reason": None,
        "last_reconcile_at": "2026-07-09T00:59:06+08:00",
    }
    book = SimpleNamespace(
        book_version="slot_20260709",
        artifact_id="slot_20260709",
        trading_day="20260709",
        updated_at="2026-07-09T14:57:28+08:00",
        daybook_effective_day="20260709",
        pulse_trade_day="20260709",
        pulse_slot_at="2026-07-09 14:55:00",
        last_closed_5m="2026-07-09 14:55:00",
        slot_status="OK",
        publish_allowed=False,
        board=[],
        tracked_universe=SimpleNamespace(total=[]),
        daybook=SimpleNamespace(
            generated_at="2026-07-09T00:59:06+08:00",
            tradeable=True,
            source_meta={"daily_freshness": dict(latest_previous_report)},
        ),
    )

    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: book)
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: latest_previous_report)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-07-08",
            "target_mode": "current_pending",
            "pending_eod_day": "2026-07-09",
            "eod_probe": {"target_day": "2026-07-09", "ready": False, "ok_count": 0},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["daily_target_day"] == "2026-07-08"
    assert runtime["daily_target_mode"] == "current_pending"
    assert runtime["daily_status"] == "eod_pending"
    assert runtime["book_freshness"] == "eod_pending"
    assert runtime["pending_eod_day"] == "2026-07-09"
    assert runtime["eod_probe"]["ready"] is False
    assert runtime["daily_checked_count"] == 30


def test_health_uses_latest_current_target_freshness_report_when_book_is_stale(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260513",
        target_pulse_trade_day="20260513",
        target_pulse_slot_at="2026-05-13 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20260101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260514",
    )
    report = {
        "ready": False,
        "target_day": "2026-05-13",
        "target_mode": "current_ready",
        "checked_count": 50,
        "stale_count": 1,
        "stale_symbols": ["002594"],
        "failed_symbols": [],
        "blocking_reason": "日线数据未补齐到 2026-05-13，当前不发布正式推荐",
        "last_reconcile_at": "2026-05-13T16:46:06+08:00",
    }

    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: report)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-05-13",
            "target_mode": "current_ready",
            "pending_eod_day": None,
            "eod_probe": {"ready": True, "ok_count": 3},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["daily_status"] == "freshness_blocked"
    assert runtime["daily_freshness_ready"] is False
    assert runtime["daily_target_day"] == "2026-05-13"
    assert runtime["daily_target_mode"] == "current_ready"
    assert runtime["daily_checked_count"] == 50
    assert runtime["daily_stale_count"] == 1
    assert runtime["daily_stale_symbols"] == ["002594"]
    assert runtime["daily_blocking_reason"] == report["blocking_reason"]


def test_health_reports_lagging_when_latest_freshness_ready_but_artifact_is_old(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260513",
        target_pulse_trade_day="20260513",
        target_pulse_slot_at="2026-05-13 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20260101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260514",
    )
    report = {
        "ready": True,
        "target_day": "2026-05-13",
        "target_mode": "current_ready",
        "checked_count": 50,
        "stale_count": 0,
        "stale_symbols": [],
        "failed_symbols": [],
        "blocking_reason": None,
        "last_reconcile_at": "2026-05-13T16:50:00+08:00",
    }
    old_artifact = SimpleNamespace(
        provider_meta={
            "reason": "daily_plan",
            "daybook_generated_at": "2026-01-01T15:01:00",
            "daily_target_day": "2026-01-01",
            "daily_target_mode": "current_pending",
            "daily_last_reconcile_at": "2026-01-01T15:00:00",
            "market_phase": "CLOSING_AUCTION",
        }
    )

    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _Book())
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(routes, "load_latest_daily_freshness_report", lambda: report)
    monkeypatch.setattr(routes, "load_slot_artifact", lambda artifact_id, trade_day=None: old_artifact)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-05-13",
            "target_mode": "current_ready",
            "pending_eod_day": None,
            "eod_probe": {"ready": True, "ok_count": 3},
        },
    )

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["daily_data_state"] == "ready"
    assert runtime["daily_status"] == "ready"
    assert runtime["daily_freshness_ready"] is True
    assert runtime["book_freshness"] == "lagging"
    assert runtime["artifact_freshness"] == "lagging"
    assert runtime["artifact_status"] == "lagging"
    assert "daily_target_day" in runtime["artifact_lag_fields"]


def test_health_reports_lagging_when_daily_ready_but_current_artifact_meta_is_stale(monkeypatch):
    state = SimpleNamespace(
        market_phase="POSTCLOSE_PENDING",
        target_daybook_effective_day="20260512",
        target_pulse_trade_day="20260512",
        target_pulse_slot_at="2026-05-12 14:55:00",
        calendar_source="official",
        calendar_status="ok",
        calendar_range_start="20260101",
        calendar_range_end="20261231",
        calendar_error=None,
        next_trading_day="20260513",
    )
    stale_artifact = SimpleNamespace(provider_meta={"reason": "daily_plan", "market_phase": "INTRADAY_AM"})

    monkeypatch.setattr(routes, "load_config", lambda: _config(True))
    monkeypatch.setattr(routes, "load_current_book", lambda: _ReadyBook())
    monkeypatch.setattr(routes, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(routes, "load_repair_status_snapshot", lambda: None)
    monkeypatch.setattr(
        routes,
        "resolve_daily_target",
        lambda *_, **__: {
            "target_day": "2026-05-11",
            "target_mode": "current_pending",
            "pending_eod_day": "2026-05-12",
            "eod_probe": None,
        },
    )
    monkeypatch.setattr(routes, "load_slot_artifact", lambda artifact_id, trade_day=None: stale_artifact)

    response = client.get("/api/health")

    assert response.status_code == 200, response.text
    runtime = response.json()["runtime"]
    assert runtime["daily_freshness_ready"] is True
    assert runtime["daily_data_state"] == "ready"
    assert runtime["daily_status"] == "ready"
    assert runtime["daily_target_day"] == "2026-05-12"
    assert runtime["daily_target_mode"] == "current_ready"
    assert runtime["daily_stale_count"] == 0
    assert runtime["book_freshness"] == "lagging"
    assert runtime["artifact_freshness"] == "lagging"
    assert runtime["artifact_status"] == "lagging"
    assert "daily_ready_current_artifact_meta_mismatch" in runtime["artifact_lag_reason"]
    assert "market_phase" in runtime["artifact_lag_fields"]
