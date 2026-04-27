from datetime import datetime

from gp_assistant.runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    compute_market_state,
    iter_trade_slots,
    last_closed_trade_slot,
)


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
