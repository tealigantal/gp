from __future__ import annotations

import pandas as pd
from pathlib import Path

from src.backtest.engine import BacktestEngine, CostModel
from src.strategies.base import Strategy, OrderIntent


class BuyAt950Strategy(Strategy):
    def __init__(self):
        super().__init__(name="t", params={})

    def on_bar(self, trade_time: str, bar_slice):
        if trade_time.endswith("09:50:00"):
            # pick first from universe
            uni = bar_slice.get("universe", [])
            if uni:
                return [OrderIntent(uni[0], "BUY", 100, reason="test_buy_0950")]
        return []


def test_friday_policies():
    # Prepare engine with one symbol and minute bars with 9:50 and 9:55
    basics = pd.DataFrame([{"ts_code": "000001.SZ", "exchange": "SZ", "is_st": False}])
    tmp_path = Path.cwd() / "results" / "tmp_test_friday"
    tmp_path.mkdir(parents=True, exist_ok=True)
    eng = BacktestEngine(
        strategies=[BuyAt950Strategy()],
        initial_cash=100000.0,
        cost_model=CostModel(min_commission=0),
        results_dir=tmp_path,
        basics=basics,
        daily_prev_close={"000001.SZ": 10.0},
    )
    bars = {
        "000001.SZ": [
            {"trade_time": "20250110 09:50:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"trade_time": "20250110 09:55:00", "open": 10.1, "high": 10.2, "low": 10.0, "close": 10.2, "vol": 100, "amount": 1010},
        ]
    }
    # Friday: no new buys, and force flat schedules sells (none yet)
    out = eng.run_day("20250110", bars, universe=["000001.SZ"], is_week_last=True)
    # Check a reject entry is recorded
    assert any(t.get("side") == "REJECT_BUY" and t.get("reason") == "friday_no_new_position" for t in eng.trades)
    # No positions opened
    assert eng.positions.get("000001.SZ", None) is None or eng.positions.get("000001.SZ").shares == 0


def test_limit_down_sell_pending_counts():
    # Prepare an engine holding shares, then SELL intent on bar close and next bar is limit down
    basics = pd.DataFrame([{"ts_code": "600000.SH", "exchange": "SH", "is_st": False}])
    tmp_path = Path.cwd() / "results" / "tmp_test_selldown"
    tmp_path.mkdir(parents=True, exist_ok=True)
    eng = BacktestEngine(
        strategies=[],
        initial_cash=100000.0,
        cost_model=CostModel(min_commission=0),
        results_dir=tmp_path,
        basics=basics,
        daily_prev_close={"600000.SH": 10.0},
    )
    # simulate we already bought earlier (previous day)
    eng.positions["600000.SH"] = type("P", (), {"ts_code": "600000.SH", "shares": 100, "cost": 10.0, "last_buy_date": "20250105"})()
    bars = {
        "600000.SH": [
            {"trade_time": "20250106 09:35:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:40:00", "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "vol": 0, "amount": 0},
        ]
    }
    # Strategy emits SELL at first bar close; engine will try at 09:40 which is limit-down one-word
    class SellFirstBar(Strategy):
        def __init__(self):
            super().__init__(name="s", params={})
        def on_bar(self, trade_time: str, bar_slice):
            if trade_time.endswith("09:35:00"):
                return [OrderIntent("600000.SH", "SELL", 100, reason="test_sell")]
            return []

    eng.strategies = [SellFirstBar()]
    out = eng.run_day("20250106", bars, universe=["600000.SH"], is_week_last=False)
    assert out["sell_fail"] >= 1
