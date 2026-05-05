from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from gp_assistant import worker
from gp_assistant.runtime.market_clock import PHASE_POSTCLOSE_PENDING, PHASE_PREOPEN


def test_reconcile_runtime_state_uses_single_dispatch_path(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="gp-worker-reconcile-"))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    preopen_state = SimpleNamespace(
        market_phase=PHASE_PREOPEN,
        target_daybook_effective_day="20240320",
        target_pulse_trade_day="20240320",
        target_pulse_slot_at=None,
    )
    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: preopen_state)
    monkeypatch.setattr(worker, "run_preopen_init", lambda now=None, force=False: {"path": "preopen", "force": force})

    auto_result = worker.reconcile_runtime_state()
    manual_result = worker.reconcile_runtime_state(operation="rebuild_daybook")

    assert auto_result["path"] == "preopen"
    assert auto_result["operation"] == "auto"
    assert manual_result["path"] == "preopen"
    assert manual_result["force"] is True
    assert manual_result["operation"] == "rebuild_daybook"


def test_postclose_archive_builds_daily_plan_without_replay(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20240320",
        target_pulse_trade_day="20240320",
        target_pulse_slot_at="2024-03-20 14:55:00",
    )
    daybook = SimpleNamespace(source_meta={"daily_freshness": {"ready": True}})
    build_calls: list[dict[str, object]] = []

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "_load_or_build_daybook", lambda trade_day, force=False: daybook)
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **kwargs: build_calls.append(kwargs) or {"artifact_id": "daily_1", "slot_status": "OK"},
    )

    result = worker.run_postclose_archive()

    assert result["archived"] is True
    assert result["artifact_id"] == "daily_1"
    assert build_calls[0]["daybook"] is daybook
    assert build_calls[0]["market_phase"] == PHASE_POSTCLOSE_PENDING


def test_replay_today_stops_when_daybook_daily_freshness_blocked(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_PREOPEN,
        target_daybook_effective_day="20240320",
        target_pulse_trade_day="20240320",
        target_pulse_slot_at="2024-03-20 10:05:00",
    )
    blocked_daybook = SimpleNamespace(
        source_meta={
            "daily_freshness": {
                "ready": False,
                "target_day": "2024-03-20",
                "stale_symbols": ["600519"],
                "failed_symbols": ["600519"],
                "blocking_reason": "日线数据未补齐到目标交易日 2024-03-20：600519",
            }
        }
    )

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "_load_or_build_daybook", lambda trade_day, force=False: blocked_daybook)

    result = worker.boot_replay_to_current_slot()

    assert result["blocked"] is True
    assert result["reason"] == "daily_freshness_blocked"
    assert "日线数据未补齐" in result["message"]


def test_load_or_build_daybook_accepts_previous_completed_daily_target(monkeypatch):
    daybook = SimpleNamespace(
        source_meta={
            "daily_freshness": {
                "ready": True,
                "target_day": "2026-04-29",
                "target_mode": "previous_completed",
            }
        }
    )
    build_calls: list[str] = []

    monkeypatch.setattr(worker, "load_daybook", lambda trade_day: daybook)
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda trade_day: {"target_day": "2026-04-29", "target_mode": "previous_completed"},
    )
    monkeypatch.setattr(worker, "build_daybook", lambda trade_day, **_: build_calls.append(trade_day) or daybook)
    monkeypatch.setattr(worker, "save_daybook", lambda built: None)

    result = worker._load_or_build_daybook("20260430")

    assert result is daybook
    assert build_calls == []


def test_postclose_archive_waits_when_eod_daily_pending(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260430",
        target_pulse_trade_day="20260430",
        target_pulse_slot_at="2026-04-30 14:55:00",
    )
    daybook = SimpleNamespace(
        source_meta={
            "daily_freshness": {
                "ready": True,
                "target_day": "2026-04-29",
                "target_mode": "current_pending",
                "pending_eod_day": "2026-04-30",
                "eod_probe": {"ready": False, "ok_count": 1},
            }
        }
    )

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "_load_or_build_daybook", lambda trade_day, force=False: daybook)

    result = worker.run_postclose_archive()

    assert result["archived"] is False
    assert result["pending"] is True
    assert result["reason"] == "eod_daily_pending"
