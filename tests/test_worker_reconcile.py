from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

from gp_assistant.book import repo
from gp_assistant.contracts.objects import (
    CurrentSlotPointer,
    DayBook,
    LiveSlotArtifact,
    SlotDataQuality,
    SlotGate,
    TrackedUniverse,
)
from gp_assistant import worker
from gp_assistant.runtime.market_clock import PHASE_POSTCLOSE_PENDING, PHASE_PREOPEN


def _daybook(
    *,
    generated_at: str = "2026-05-12T16:52:00+08:00",
    target_day: str = "2026-05-12",
    target_mode: str = "current_ready",
    last_reconcile_at: str = "2026-05-12T16:52:00+08:00",
) -> DayBook:
    return DayBook(
        trading_day="20260512",
        generated_at=generated_at,
        tradeable=True,
        source_meta={
            "daily_freshness": {
                "ready": True,
                "target_day": target_day,
                "target_mode": target_mode,
                "checked_count": 50,
                "stale_count": 0,
                "last_reconcile_at": last_reconcile_at,
            }
        },
    )


def _artifact(
    *,
    artifact_id: str = "daily_old",
    market_phase: str = "INTRADAY_AM",
    provider_meta: dict | None = None,
) -> LiveSlotArtifact:
    return LiveSlotArtifact(
        artifact_id=artifact_id,
        slot_id=None,
        trade_day="20260512",
        slot_at=None,
        market_phase=market_phase,
        slot_status="OK",
        publish_allowed=True,
        daybook_effective_day="20260512",
        gate=SlotGate(state="ALLOW", score=100.0, reasons=["daily_plan"]),
        tracked_universe=TrackedUniverse(reco=[], reserve=[], portfolio=[], total=[]),
        board=[],
        symbol_states={},
        data_quality=SlotDataQuality(
            symbols_expected=0,
            symbols_received=0,
            benchmark_received=True,
            provider="daily",
            complete=True,
        ),
        portfolio_snapshot={},
        provider_meta=provider_meta if provider_meta is not None else {"reason": "daily_plan"},
        created_at="2026-05-12T10:42:54+08:00",
        updated_at="2026-05-12T10:42:54+08:00",
    )


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


def test_auto_reconcile_uses_postclose_archive_in_postclose_pending(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260512",
        target_pulse_trade_day="20260512",
        target_pulse_slot_at="2026-05-12 14:55:00",
    )
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "run_preopen_init", lambda **_: (_ for _ in ()).throw(AssertionError("preopen path should not run")))
    monkeypatch.setattr(
        worker,
        "run_postclose_archive",
        lambda now=None, force=False: calls.append({"force": force}) or {"path": "postclose", "force": force},
    )

    result = worker.reconcile_runtime_state(operation="auto")

    assert result["path"] == "postclose"
    assert result["force"] is False
    assert result["operation"] == "auto"
    assert calls == [{"force": False}]


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
    assert result["daily_status"] == "ready"
    assert result["artifact_id"] == "daily_1"
    assert build_calls[0]["daybook"] is daybook
    assert build_calls[0]["market_phase"] == PHASE_POSTCLOSE_PENDING


def test_auto_postclose_rebuilds_current_artifact_when_old_artifact_lacks_freshness_meta(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="gp-worker-postclose-old-"))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260512",
        target_pulse_trade_day="20260512",
        target_pulse_slot_at="2026-05-12 14:55:00",
    )
    daybook = _daybook()
    old_artifact = _artifact(artifact_id="daily_old", market_phase="INTRADAY_AM", provider_meta={"reason": "daily_plan"})
    repo.save_daybook(daybook)
    repo.save_slot_artifact(old_artifact)
    repo.save_current_pointer(
        CurrentSlotPointer(
            artifact_id=old_artifact.artifact_id,
            trade_day=old_artifact.trade_day,
            slot_id=old_artifact.slot_id,
            slot_at=old_artifact.slot_at,
            updated_at=old_artifact.updated_at,
        )
    )

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda trade_day: {"target_day": "2026-05-12", "target_mode": "current_ready"},
    )
    monkeypatch.setattr(worker, "load_portfolio_snapshot", lambda: {"positions": []})

    result = worker.reconcile_runtime_state(operation="auto")
    current = repo.load_current_slot_artifact()

    assert result["archived"] is True
    assert result["daily_status"] == "ready"
    assert result.get("noop") is not True
    assert current is not None
    assert current.artifact_id != "daily_old"
    assert current.market_phase == PHASE_POSTCLOSE_PENDING
    assert current.provider_meta["daily_target_day"] == "2026-05-12"
    assert current.provider_meta["daily_target_mode"] == "current_ready"
    assert current.provider_meta["daily_last_reconcile_at"] == "2026-05-12T16:52:00+08:00"
    assert current.provider_meta["daybook_generated_at"] == "2026-05-12T16:52:00+08:00"


def test_build_daily_plan_noops_only_when_freshness_meta_matches(monkeypatch):
    temp_root = Path(tempfile.mkdtemp(prefix="gp-worker-noop-meta-"))
    monkeypatch.setenv("GP_STORE_DIR", str(temp_root / "store"))
    daybook = _daybook()
    matching_meta = {
        "reason": "daily_plan",
        "daybook_generated_at": "2026-05-12T16:52:00+08:00",
        "daily_target_day": "2026-05-12",
        "daily_target_mode": "current_ready",
        "daily_last_reconcile_at": "2026-05-12T16:52:00+08:00",
        "market_phase": PHASE_POSTCLOSE_PENDING,
    }
    current_artifact = _artifact(artifact_id="daily_current", market_phase=PHASE_POSTCLOSE_PENDING, provider_meta=matching_meta)
    repo.save_daybook(daybook)
    repo.save_slot_artifact(current_artifact)
    repo.save_current_pointer(
        CurrentSlotPointer(
            artifact_id=current_artifact.artifact_id,
            trade_day=current_artifact.trade_day,
            slot_id=current_artifact.slot_id,
            slot_at=current_artifact.slot_at,
            updated_at=current_artifact.updated_at,
        )
    )
    monkeypatch.setattr(worker, "load_portfolio_snapshot", lambda: {"positions": []})

    result = worker._build_and_save_daily_plan(
        daybook=daybook,
        trade_day="20260512",
        market_phase=PHASE_POSTCLOSE_PENDING,
        force=False,
    )

    assert result["noop"] is True
    assert result["artifact_id"] == "daily_current"


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


def test_load_or_build_daybook_keeps_current_ready_freshness_when_probe_later_pending(monkeypatch):
    daybook = _daybook()
    build_calls: list[str] = []

    monkeypatch.setattr(worker, "load_daybook", lambda trade_day: daybook)
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda trade_day: {
            "target_day": "2026-05-11",
            "target_mode": "current_pending",
            "pending_eod_day": "2026-05-12",
        },
    )
    monkeypatch.setattr(worker, "build_daybook", lambda trade_day, **_: build_calls.append(trade_day) or daybook)
    monkeypatch.setattr(worker, "save_daybook", lambda built: None)

    result = worker._load_or_build_daybook("20260512")

    assert result is daybook
    assert build_calls == []


def test_load_or_build_daybook_updates_pending_eod_probe_without_rebuilding(monkeypatch):
    daybook = _daybook(target_day="2026-05-11", target_mode="previous_completed")
    build_calls: list[str] = []
    saved: list[DayBook] = []

    monkeypatch.setattr(worker, "load_daybook", lambda trade_day: daybook)
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda trade_day: {
            "target_day": "2026-05-11",
            "target_mode": "current_pending",
            "pending_eod_day": "2026-05-12",
            "eod_probe": {"ready": False, "ok_count": 1, "next_retry_after": "2026-05-12T17:05:00+08:00"},
        },
    )
    monkeypatch.setattr(worker, "build_daybook", lambda trade_day, **_: build_calls.append(trade_day) or daybook)
    monkeypatch.setattr(worker, "save_daybook", lambda built: saved.append(built))

    result = worker._load_or_build_daybook("20260512")

    freshness = result.source_meta["daily_freshness"]
    assert result is daybook
    assert freshness["target_mode"] == "current_pending"
    assert freshness["pending_eod_day"] == "2026-05-12"
    assert freshness["eod_probe"]["next_retry_after"] == "2026-05-12T17:05:00+08:00"
    assert build_calls == []
    assert saved == [daybook]


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
    assert result["daily_status"] == "eod_pending"


def test_postclose_archive_persists_blocked_current_day_freshness_without_publishing(monkeypatch):
    state = SimpleNamespace(
        market_phase=PHASE_POSTCLOSE_PENDING,
        target_daybook_effective_day="20260513",
        target_pulse_trade_day="20260513",
        target_pulse_slot_at="2026-05-13 14:55:00",
    )
    stale_daybook = _daybook(target_day="2026-05-12", target_mode="current_pending")
    stale_daybook.trading_day = "20260513"
    blocked_daybook = _daybook(target_day="2026-05-13", target_mode="current_ready")
    blocked_daybook.trading_day = "20260513"
    blocked_daybook.source_meta["daily_freshness"].update(
        {
            "ready": False,
            "stale_count": 1,
            "stale_symbols": ["002594"],
            "blocking_reason": "日线数据未补齐到 2026-05-13，当前不发布正式推荐",
        }
    )
    saved: list[DayBook] = []

    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: state)
    monkeypatch.setattr(worker, "load_daybook", lambda trade_day: stale_daybook)
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda trade_day: {"target_day": "2026-05-13", "target_mode": "current_ready", "pending_eod_day": None},
    )
    monkeypatch.setattr(worker, "build_daybook", lambda trade_day, **_: blocked_daybook)
    monkeypatch.setattr(worker, "save_daybook", lambda daybook: saved.append(daybook))
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **_: (_ for _ in ()).throw(AssertionError("blocked daily freshness must not publish")),
    )

    result = worker.run_postclose_archive()

    assert saved == [blocked_daybook]
    assert result["blocked"] is True
    assert result["reason"] == "daily_freshness_blocked"
    assert result["daily_status"] == "freshness_blocked"
    assert result["daily_freshness"]["target_day"] == "2026-05-13"


def test_auto_postclose_waits_when_eod_probe_is_pending(monkeypatch):
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
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **_: (_ for _ in ()).throw(AssertionError("pending EOD must not publish")),
    )

    result = worker.reconcile_runtime_state(operation="auto")

    assert result["pending"] is True
    assert result["reason"] == "eod_daily_pending"
    assert result["operation"] == "auto"
