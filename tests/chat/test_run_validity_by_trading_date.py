from __future__ import annotations

from datetime import datetime

from gp_assistant.selection_engine.trading_clock import is_run_valid_for_operation


def _dt(s: str) -> datetime:
    # interpret as Asia/Shanghai without external tz dependency
    # naive datetime is acceptable because trading_clock compares dates only for resolve
    return datetime.fromisoformat(s)


def test_friday_intraday_invalid_after_close():
    art = {
        "run_id": "rid-intra",
        "trading_date": "2024-03-08",  # Friday
        "as_of": "2024-03-08",
        "as_of_ts": "2024-03-08T14:30:00",
        "data_cutoff": "INTRADAY",
        "symbols": [],
        "themes": [],
        "items": [],
        "degraded": False,
        "tradeable": True,
    }
    now = _dt("2024-03-08T15:10:00")
    assert is_run_valid_for_operation(art, now, operation="recommend") is False


def test_friday_eod_valid_on_weekend_and_preopen():
    art = {
        "run_id": "rid-eod",
        "trading_date": "2024-03-08",  # Friday
        "as_of": "2024-03-08",
        "as_of_ts": "2024-03-08T20:00:00",
        "data_cutoff": "EOD",
        "symbols": [],
        "themes": [],
        "items": [],
        "degraded": False,
        "tradeable": True,
    }
    # Weekend
    sat = _dt("2024-03-09T10:00:00")
    sun = _dt("2024-03-10T10:00:00")
    mon_pre = _dt("2024-03-11T09:10:00")
    assert is_run_valid_for_operation(art, sat, operation="recommend") is True
    assert is_run_valid_for_operation(art, sun, operation="recommend") is True
    assert is_run_valid_for_operation(art, mon_pre, operation="recommend") is True
