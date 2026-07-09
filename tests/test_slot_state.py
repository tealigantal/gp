from __future__ import annotations

from types import SimpleNamespace

from gp_assistant.runtime.slot_state import build_runtime_state_snapshot


def _market_state(phase="POSTCLOSE_PENDING", target_slot="2026-07-09 14:55:00"):
    return SimpleNamespace(
        market_phase=phase,
        data_status="close_pending" if phase == "POSTCLOSE_PENDING" else "ok",
        target_daybook_effective_day="20260709",
        target_pulse_trade_day="20260709",
        target_pulse_slot_at=target_slot,
    )


def _book(*, publish_allowed=False, pulse_slot_at=None, target_day="2026-07-09", target_mode="current_ready"):
    freshness = {
        "ready": True,
        "target_day": target_day,
        "target_mode": target_mode,
        "checked_count": 3,
        "stale_count": 0,
        "last_reconcile_at": "2026-07-09T17:00:00+08:00",
    }
    daybook = SimpleNamespace(
        generated_at="2026-07-09T17:00:01+08:00",
        source_meta={"daily_freshness": freshness},
    )
    return SimpleNamespace(
        artifact_id="daily_1",
        trading_day="20260709",
        daybook=daybook,
        daybook_effective_day="20260709",
        publish_allowed=publish_allowed,
        pulse_slot_at=pulse_slot_at,
        last_closed_5m=pulse_slot_at,
        slot_status="OK",
        gate=SimpleNamespace(state="ALLOW"),
    )


def _daily_artifact(**meta_overrides):
    provider_meta = {
        "chain": "runtime",
        "runtime_stage": "daily",
        "reason": "daily_plan",
        "data_status": "daily_plan",
        "daybook_generated_at": "2026-07-09T17:00:01+08:00",
        "daily_target_day": "2026-07-09",
        "daily_target_mode": "current_ready",
        "daily_last_reconcile_at": "2026-07-09T17:00:00+08:00",
        "market_phase": "POSTCLOSE_PENDING",
    }
    provider_meta.update(meta_overrides)
    return SimpleNamespace(
        artifact_id="daily_1",
        trade_day="20260709",
        slot_at=None,
        provider_meta=provider_meta,
    )


def test_postclose_daily_ready_is_runtime_state_not_clock_phase():
    state = build_runtime_state_snapshot(
        book=_book(publish_allowed=False),
        market_state=_market_state(),
        daily_target={"target_day": "2026-07-09", "target_mode": "current_ready"},
        latest_freshness_report={},
        current_artifact=_daily_artifact(),
        intraday_runtime_enabled=True,
    )

    assert state.market_phase == "POSTCLOSE_PENDING"
    assert state.clock_data_status == "close_pending"
    assert state.daily_data_state == "ready"
    assert state.artifact_stage == "daily_plan"
    assert state.artifact_freshness == "current"
    assert state.book_freshness == "postclose_ready"
    assert state.tradeability_state == "no_trade"


def test_artifact_lag_is_not_encoded_as_daily_status():
    state = build_runtime_state_snapshot(
        book=_book(),
        market_state=_market_state(),
        daily_target={"target_day": "2026-07-09", "target_mode": "current_ready"},
        latest_freshness_report={},
        current_artifact=_daily_artifact(market_phase="CLOSING_AUCTION"),
        intraday_runtime_enabled=True,
    )

    assert state.daily_data_state == "ready"
    assert state.artifact_freshness == "lagging"
    assert state.artifact_status == "lagging"
    assert state.book_freshness == "lagging"
    assert "market_phase" in state.artifact_lag_fields


def test_lunch_uses_last_closed_slot_without_daily_lag():
    artifact = SimpleNamespace(
        artifact_id="slot_1",
        trade_day="20260709",
        slot_at="2026-07-09 11:30:00",
        provider_meta={"chain": "runtime", "runtime_stage": "minute", "reason": "intraday_pulse"},
    )
    state = build_runtime_state_snapshot(
        book=_book(pulse_slot_at="2026-07-09 11:30:00", target_day="2026-07-08", target_mode="previous_completed"),
        market_state=_market_state(phase="LUNCH_BREAK", target_slot="2026-07-09 11:30:00"),
        daily_target={"target_day": "2026-07-08", "target_mode": "previous_completed"},
        latest_freshness_report={},
        current_artifact=artifact,
        intraday_runtime_enabled=True,
    )

    assert state.daily_data_state == "previous_completed"
    assert state.artifact_stage == "intraday_pulse"
    assert state.artifact_freshness == "current"
    assert state.book_freshness == "intraday_ready"
