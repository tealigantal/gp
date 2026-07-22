from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from gp_assistant import worker
from gp_assistant.contracts.objects import DayBook, TurnFrame
from gp_assistant.contracts.runtime import require_runtime_operation
from gp_assistant.evidence.daily_freshness import (
    TARGET_CURRENT_PENDING,
    TARGET_CURRENT_READY,
    TARGET_PREVIOUS_COMPLETED,
    daily_freshness_target_fields,
)
from gp_assistant.runtime.market_clock import (
    PHASE_LUNCH_BREAK,
    PHASE_POSTCLOSE_PENDING,
    PHASE_PREOPEN,
)
from gp_assistant.runtime.market_time import MarketTimeContext
from gp_assistant.runtime.producer import producer_metadata


def _market_time(
    *,
    mode: str = TARGET_CURRENT_READY,
    phase: str = PHASE_PREOPEN,
    effective_day: str = "2026-05-12",
    pulse_slot: str | None = None,
) -> MarketTimeContext:
    return MarketTimeContext(
        decision_trade_day="2026-05-12",
        daybook_effective_day=effective_day,
        pulse_trade_day="2026-05-12" if pulse_slot else None,
        pulse_slot_closed_at=pulse_slot,
        observed_at="2026-05-12T10:00:00+08:00",
        market_phase=phase,
        target_mode=mode,
        pending_eod_day="2026-05-12" if mode == TARGET_CURRENT_PENDING else None,
    )


def _daybook(*, mode: str = TARGET_CURRENT_READY, ready: bool = True) -> DayBook:
    return DayBook(
        trading_day="20260512",
        generated_at="2026-05-12T09:00:00+08:00",
        source_meta={
            "decision": "no_trade",
            "daily_freshness": {
                "ready": ready,
                "target_day": "2026-05-12",
                "target_mode": mode,
                "checked_count": 1,
                "stale_count": 0 if ready else 1,
                "blocking_reason": None if ready else "日线数据未补齐到目标交易日",
            },
        },
        producer=producer_metadata(),
    )


def _state(*, phase: str, pulse_slot: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        market_phase=phase,
        target_daybook_effective_day="20260512",
        target_pulse_trade_day="20260512" if pulse_slot else None,
        target_pulse_slot_at=pulse_slot,
    )


def test_runtime_operation_contract_has_only_resident_paths():
    assert require_runtime_operation("auto") == "auto"
    assert require_runtime_operation("rebuild_daybook") == "rebuild_daybook"
    assert require_runtime_operation("postclose_archive") == "postclose_archive"
    for retired in ("replay_today", "daily-loop", "preopen", ""):
        with pytest.raises(ValueError, match="runtime_operation_invalid"):
            require_runtime_operation(retired)


def test_worker_exposes_no_retired_runtime_or_storage_shims():
    for name in (
        "boot_replay_to_current_slot",
        "replay_today_once",
        "run_daily_loop",
        "run_postclose_archive",
        "run_preopen_init",
        "load_daybook",
        "load_portfolio_snapshot",
    ):
        assert not hasattr(worker, name)


def test_reconcile_runtime_state_uses_the_single_validated_dispatch(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        worker,
        "run_runtime_chain",
        lambda *, now=None, operation="auto": calls.append(operation)
        or {"runtime_chain": True, "operation": operation},
    )

    auto = worker.reconcile_runtime_state()
    rebuilt = worker.reconcile_runtime_state(operation="rebuild_daybook")

    assert auto["operation"] == "auto"
    assert rebuilt["operation"] == "rebuild_daybook"
    assert calls == ["auto", "rebuild_daybook"]
    with pytest.raises(ValueError, match="runtime_operation_invalid"):
        worker.reconcile_runtime_state(operation="replay_today")


def test_runtime_chain_uses_canonical_market_time_for_intraday_dispatch(monkeypatch):
    market_time = _market_time(
        phase=PHASE_LUNCH_BREAK,
        pulse_slot="2026-05-12 11:30:00",
    )
    daybook = _daybook()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(
            intraday_runtime_enabled=True,
            intraday_benchmark_symbol="000300",
        ),
    )
    monkeypatch.setattr(
        worker,
        "compute_market_state",
        lambda now=None: _state(
            phase=PHASE_LUNCH_BREAK,
            pulse_slot="2026-05-12 11:30:00",
        ),
    )
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        worker,
        "_load_or_build_daybook",
        lambda value, force=False: captured.update(
            {"market_time": value, "force": force}
        )
        or daybook,
    )
    monkeypatch.setattr(
        worker,
        "AgentStore",
        lambda: SimpleNamespace(current_snapshot=lambda: None),
    )
    monkeypatch.setattr(
        worker,
        "_build_and_save_runtime_artifact",
        lambda **kwargs: captured.update(kwargs)
        or {"artifact_id": "slot-current", "slot_status": "OK"},
    )

    result = worker.run_runtime_chain()

    assert captured["market_time"] is market_time
    assert captured["trade_day"] == "20260512"
    assert captured["target_slot_at"] == "2026-05-12 11:30:00"
    assert captured["enable_minutes"] is True
    assert result["operation"] == "auto"
    assert result["capabilities"] == {
        "daily": True,
        "minutes": True,
        "portfolio": False,
    }


def test_postclose_archive_is_an_explicit_runtime_operation(monkeypatch):
    market_time = _market_time(phase=PHASE_POSTCLOSE_PENDING)
    daybook = _daybook()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(intraday_runtime_enabled=False),
    )
    monkeypatch.setattr(
        worker,
        "compute_market_state",
        lambda now=None: _state(phase=PHASE_POSTCLOSE_PENDING),
    )
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        worker,
        "_load_or_build_daybook",
        lambda value, force=False: captured.update(
            {"market_time": value, "force": force}
        )
        or daybook,
    )
    monkeypatch.setattr(
        worker,
        "AgentStore",
        lambda: SimpleNamespace(current_snapshot=lambda: None),
    )
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **kwargs: captured.update(kwargs)
        or {"artifact_id": "daily-current", "slot_status": "OK"},
    )

    result = worker.run_runtime_chain(operation="postclose_archive")

    assert captured["force"] is True
    assert captured["market_time"] is market_time
    assert captured["market_phase"] == PHASE_POSTCLOSE_PENDING
    assert result["operation"] == "postclose_archive"
    assert result["archived"] is True


def test_pending_eod_returns_explicit_daily_freshness_projection(monkeypatch):
    market_time = _market_time(mode=TARGET_CURRENT_PENDING)
    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(intraday_runtime_enabled=False),
    )
    monkeypatch.setattr(
        worker,
        "compute_market_state",
        lambda now=None: _state(phase=PHASE_POSTCLOSE_PENDING),
    )
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        worker,
        "_load_or_build_daybook",
        lambda *_args, **_kwargs: pytest.fail(
            "pending EOD must not build or publish a daybook"
        ),
    )

    result = worker.run_runtime_chain()

    assert result["pending"] is True
    assert result["reason"] == "eod_daily_pending"
    assert result["daily_freshness"] == daily_freshness_target_fields(
        market_time
    )


def test_blocked_daily_freshness_does_not_publish(monkeypatch):
    market_time = _market_time()
    blocked = _daybook(ready=False)
    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(intraday_runtime_enabled=False),
    )
    monkeypatch.setattr(
        worker,
        "compute_market_state",
        lambda now=None: _state(phase=PHASE_PREOPEN),
    )
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        worker,
        "_load_or_build_daybook",
        lambda *_args, **_kwargs: blocked,
    )
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **_kwargs: pytest.fail(
            "blocked daily freshness must not publish"
        ),
    )

    result = worker.run_runtime_chain()

    assert result["blocked"] is True
    assert result["reason"] == "daily_freshness_blocked"
    assert result["daily_status"] == "freshness_blocked"


def test_incomplete_full_market_universe_publishes_explicit_no_trade(monkeypatch):
    market_time = _market_time()
    blocked = _daybook(ready=False)
    blocked.source_meta["daily_freshness"].update(
        {
            "universe_id": "mus_20260512_incomplete",
            "blocking_reason": "candidate_universe_incomplete",
        }
    )
    calls: list[dict] = []
    monkeypatch.setattr(worker, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=False))
    monkeypatch.setattr(worker, "compute_market_state", lambda now=None: _state(phase=PHASE_PREOPEN))
    monkeypatch.setattr(worker, "resolve_daily_target", lambda **_kwargs: market_time)
    monkeypatch.setattr(worker, "_load_or_build_daybook", lambda *_args, **_kwargs: blocked)
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **kwargs: calls.append(kwargs) or {"artifact_id": "daily-no-trade"},
    )

    result = worker.run_runtime_chain()

    assert calls and calls[0]["daybook"] is blocked
    assert result["artifact_id"] == "daily-no-trade"
    assert result["reason"] == "candidate_universe_incomplete"
    assert result["blocked"] is True


def test_noop_requires_the_current_snapshot_to_match_market_time_and_daybook(
    monkeypatch,
):
    market_time = _market_time(mode=TARGET_PREVIOUS_COMPLETED)
    daybook = _daybook(mode=TARGET_PREVIOUS_COMPLETED)
    snapshot = SimpleNamespace(snapshot_id="snapshot-current")

    monkeypatch.setattr(
        worker,
        "load_config",
        lambda: SimpleNamespace(intraday_runtime_enabled=False),
    )
    monkeypatch.setattr(
        worker,
        "compute_market_state",
        lambda now=None: _state(phase=PHASE_PREOPEN),
    )
    monkeypatch.setattr(
        worker,
        "resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        worker,
        "_load_or_build_daybook",
        lambda *_args, **_kwargs: daybook,
    )
    monkeypatch.setattr(
        worker,
        "AgentStore",
        lambda: SimpleNamespace(current_snapshot=lambda: snapshot),
    )
    monkeypatch.setattr(worker, "_snapshot_matches_market_time", lambda *_: True)
    monkeypatch.setattr(worker, "_snapshot_contains_daybook", lambda *_: True)
    monkeypatch.setattr(
        worker,
        "_build_and_save_daily_plan",
        lambda **_kwargs: pytest.fail(
            "matching current snapshot must not be republished"
        ),
    )

    result = worker.run_runtime_chain()

    assert result["noop"] is True
    assert result["artifact_id"] == "snapshot-current"


def test_load_or_build_daybook_uses_agent_store_and_market_time_contract(
    monkeypatch,
):
    daybook = _daybook(mode=TARGET_PREVIOUS_COMPLETED)
    daybook.source_meta["candidate_universe"] = {
        "schema": "MarketUniverseSnapshot.v1",
        "complete": True,
    }
    market_time = _market_time(mode=TARGET_PREVIOUS_COMPLETED)
    captured: dict[str, object] = {}

    class Store:
        def load_daybook(self, effective_day, *, producer):
            captured["effective_day"] = effective_day
            captured["producer"] = producer
            return daybook

    monkeypatch.setattr(worker, "AgentStore", Store)
    monkeypatch.setattr(
        worker,
        "build_daybook",
        lambda *_args, **_kwargs: pytest.fail(
            "a producer-compatible stored daybook must be reused"
        ),
    )

    result = worker._load_or_build_daybook(market_time)

    assert result is daybook
    assert captured["effective_day"] == "2026-05-12"
    assert captured["producer"] == producer_metadata()


def test_daily_freshness_projection_is_explicit_and_market_time_stays_canonical():
    market_time = _market_time(mode=TARGET_PREVIOUS_COMPLETED)

    assert market_time.as_dict()["daybook_effective_day"] == "2026-05-12"
    assert "target_day" not in market_time.as_dict()
    assert daily_freshness_target_fields(market_time)["target_day"] == "2026-05-12"


def test_intent_contract_rejects_retired_labels():
    with pytest.raises(ValidationError):
        TurnFrame(
            frame_id="frame",
            raw_message="解释",
            subject="pick",
            request="explain",
            freshness="active_run",
        )
    with pytest.raises(ValidationError):
        TurnFrame(
            frame_id="frame",
            raw_message="现在能买吗",
            subject="symbol",
            request="live_entry_check",
            freshness="latest_5m",
        )
