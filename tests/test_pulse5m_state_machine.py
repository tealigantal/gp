from __future__ import annotations

import pandas as pd

from gp_assistant.book.pulse5m import evaluate_slot_pulses
from gp_assistant.contracts.objects import AdvicePick, DayBook, SlotGate, TrackedUniverse


def _bars(close_values, *, vols):
    times = pd.date_range("2024-03-20 09:35:00", periods=len(close_values), freq="5min")
    rows = []
    prev = 10.0
    for idx, close in enumerate(close_values):
        open_px = prev
        rows.append(
            {
                "trade_time": times[idx],
                "open": open_px,
                "high": max(open_px, close) + 0.03,
                "low": min(open_px, close) - 0.02,
                "close": close,
                "vol": vols[idx],
                "amount": close * vols[idx],
            }
        )
        prev = close
    return pd.DataFrame(rows)


def test_breakout_buy_maps_to_buy_when_gate_allows():
    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                industry="白酒",
                entry_plan={"high": 10.30, "mid": 10.18},
                stop_plan={"price": 9.85},
                take_profit_plan={"targets": [10.80]},
            )
        ],
    )
    tracked = TrackedUniverse(reco=["600519"], reserve=[], portfolio=[], total=["600519"])
    symbol_bars = _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150])
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100, 100, 100, 100, 100, 100, 100])

    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked,
        bars={"600519": symbol_bars},
        benchmark=benchmark,
        slot_baselines={"600519": {"10:05": 100.0}},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="akshare",
    )
    pulse = pulses["600519"]
    assert pulse.execution_state == "breakout_buy"
    assert pulse.action == "BUY"
    assert pulse.can_open is True


def test_breakout_buy_is_forced_to_watch_when_gate_blocked():
    daybook = DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                industry="白酒",
                entry_plan={"high": 10.30, "mid": 10.18},
                stop_plan={"price": 9.85},
                take_profit_plan={"targets": [10.80]},
            )
        ],
    )
    tracked = TrackedUniverse(reco=["600519"], reserve=[], portfolio=[], total=["600519"])
    symbol_bars = _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150])
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100, 100, 100, 100, 100, 100, 100])

    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=tracked,
        bars={"600519": symbol_bars},
        benchmark=benchmark,
        slot_baselines={"600519": {"10:05": 100.0}},
        gate=SlotGate(state="BLOCKED", score=40.0, reasons=["blocked"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="akshare",
    )
    pulse = pulses["600519"]
    assert pulse.execution_state == "breakout_buy"
    assert pulse.action == "WATCH"
    assert pulse.can_open is False
