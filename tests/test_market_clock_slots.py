from datetime import datetime

import pandas as pd
import pytest

import gp_assistant.runtime.market_clock as market_clock
from gp_assistant.runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_NON_TRADING,
    _last_open_day_on_or_before,
    compute_market_state,
    iter_trade_slots,
    last_closed_trade_slot,
)


@pytest.fixture(autouse=True)
def _calendar(monkeypatch):
    cal = pd.DataFrame(
        [
            {"cal_date": "20240319", "is_open": 1},
            {"cal_date": "20240320", "is_open": 1},
            {"cal_date": "20240321", "is_open": 1},
            {"cal_date": "20260429", "is_open": 1},
            {"cal_date": "20260430", "is_open": 1},
            {"cal_date": "20260501", "is_open": 0},
            {"cal_date": "20260502", "is_open": 0},
            {"cal_date": "20260503", "is_open": 0},
            {"cal_date": "20260504", "is_open": 0},
            {"cal_date": "20260505", "is_open": 0},
            {"cal_date": "20260506", "is_open": 1},
        ]
    )
    monkeypatch.setattr(market_clock, "_load_calendar_df", lambda: cal)


def test_last_closed_trade_slot_handles_pm_first_bar_gap():
    assert last_closed_trade_slot(datetime(2024, 3, 20, 13, 2)).strftime("%H:%M") == "11:30"
    assert last_closed_trade_slot(datetime(2024, 3, 20, 13, 7)).strftime("%H:%M") == "13:05"


def test_market_phase_handles_lunch_and_closing_auction():
    assert compute_market_state(datetime(2024, 3, 20, 11, 45)).market_phase == PHASE_LUNCH_BREAK
    assert compute_market_state(datetime(2024, 3, 20, 14, 58)).market_phase == PHASE_CLOSING_AUCTION
    assert compute_market_state(datetime(2024, 3, 20, 13, 10)).market_phase == PHASE_INTRADAY_PM


def test_iter_trade_slots_covers_two_sessions_without_1500_slot():
    slots = iter_trade_slots("20240320")
    assert slots[0].strftime("%H:%M") == "09:35"
    assert slots[-1].strftime("%H:%M") == "14:55"
    assert "15:00" not in {slot.strftime("%H:%M") for slot in slots}


def test_last_open_day_uses_calendar_without_weekday_fallback_when_calendar_is_stale():
    stale_calendar = pd.DataFrame(
        [
            {"cal_date": "20250109", "is_open": 1},
            {"cal_date": "20250110", "is_open": 1},
        ]
    )

    result = _last_open_day_on_or_before(pd.Timestamp("2026-04-29"), stale_calendar)

    assert result.strftime("%Y%m%d") == "20250110"


def test_labour_day_holiday_uses_previous_completed_day_and_next_open():
    ms = compute_market_state(datetime(2026, 5, 4, 10, 0))

    assert ms.market_phase == PHASE_NON_TRADING
    assert ms.is_trading_day is False
    assert ms.target_daybook_effective_day == "20260430"
    assert ms.target_pulse_trade_day is None
    assert ms.next_trading_day == "20260506"
    assert ms.calendar_status == "ok"


def test_calendar_out_of_range_fails_closed(monkeypatch):
    stale_calendar = pd.DataFrame(
        [
            {"cal_date": "20250109", "is_open": 1},
            {"cal_date": "20250110", "is_open": 1},
        ]
    )
    monkeypatch.setattr(market_clock, "_load_calendar_df", lambda: stale_calendar)

    ms = compute_market_state(datetime(2026, 4, 29, 10, 0))

    assert ms.market_phase == PHASE_NON_TRADING
    assert ms.is_trading_day is False
    assert ms.calendar_status == "out_of_range"
    assert ms.target_daybook_effective_day == "20250110"
