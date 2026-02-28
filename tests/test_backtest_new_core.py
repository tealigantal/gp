from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from src.selector.selector_v1 import explainable_score, SelectorConfig
from src.backtest.engine import BacktestEngine, CostModel, Position, Order
from src.strategies.base import Strategy, OrderIntent


def test_no_lookahead_in_selector():
    # two symbols: A has poor history but huge current-day spike; B has better prior history
    daily = pd.DataFrame(
        [
            # A prior
            {"ts_code": "000001.SZ", "trade_date": "20250103", "open": 10, "high": 10, "low": 10, "close": 10, "vol": 100, "amount": 1000},
            {"ts_code": "000001.SZ", "trade_date": "20250104", "open": 10, "high": 10, "low": 10, "close": 8.0, "vol": 100, "amount": 1000},
            # B prior
            {"ts_code": "600000.SH", "trade_date": "20250103", "open": 10, "high": 10, "low": 10, "close": 11.0, "vol": 100, "amount": 1000},
            {"ts_code": "600000.SH", "trade_date": "20250104", "open": 11.0, "high": 11.0, "low": 11.0, "close": 12.0, "vol": 100, "amount": 1000},
        ]
    )
    # ann today is empty
    anns = pd.DataFrame(columns=["ts_code", "ann_date", "title", "category"])  # today: 20250106
    cfg = SelectorConfig(trend_window=2, momentum_window=1, liquidity_window=1, vol_penalty_window=2)
    scores = explainable_score(daily, anns, cfg)
    # B should rank above A from prior momentum/trend
    assert scores.iloc[0]["ts_code"] == "600000.SH"


def test_tplus_one_enforced():
    tmp_path = Path.cwd() / "results" / "tmp_test_t1"
    tmp_path.mkdir(parents=True, exist_ok=True)
    basics = pd.DataFrame([{"ts_code": "000001.SZ", "exchange": "SZ", "is_st": False}])
    eng = BacktestEngine(
        strategies=[],
        initial_cash=100000.0,
        cost_model=CostModel(min_commission=0),
        results_dir=tmp_path,
        basics=basics,
        daily_prev_close={"000001.SZ": 10.0},
    )
    # Create two bars same day
    bars = {
        "000001.SZ": [
            {"trade_time": "20250106 09:35:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:40:00", "open": 10.2, "high": 10.2, "low": 10.2, "close": 10.2, "vol": 100, "amount": 1020},
        ]
    }
    # schedule: buy at 09:40 open (after 09:35 close), then sell on same day next bar (which doesn't exist -> none)
    universe = ["000001.SZ"]
    # We mimic a strategy by injecting scheduled orders around run_day process: create intents via algorithm
    # To simplify, we call run_day and then attempt a same-day sell via a synthetic order at second bar.
    # First, submit a buy scheduled after first close
    # Use engine internal by creating an Order executed at second bar
    # run_day will also create the timeline; here we simulate fills directly
    # Execute BUY at 09:40 open
    order_buy = Order(ts_code="000001.SZ", side="BUY", shares=100, signal_time="20250106 09:35:00", next_exec_time="20250106 09:40:00")
    # Fill buy
    assert eng._exec_order(order_buy, bar_open=10.2, trade_time="20250106 09:40:00")
    # Try to SELL on same day 09:45 (T+1 should block)
    order_sell = Order(ts_code="000001.SZ", side="SELL", shares=100, signal_time="20250106 09:40:00", next_exec_time="20250106 09:45:00")
    filled = eng._exec_order(order_sell, bar_open=10.1, trade_time="20250106 09:45:00")
    assert filled is False


def test_one_word_limit_pending_counts():
    tmp_path = Path.cwd() / "results" / "tmp_test_limit"
    tmp_path.mkdir(parents=True, exist_ok=True)
    basics = pd.DataFrame([{"ts_code": "000001.SZ", "exchange": "SZ", "is_st": False}])
    eng = BacktestEngine(
        strategies=[],
        initial_cash=100000.0,
        cost_model=CostModel(min_commission=0),
        results_dir=tmp_path,
        basics=basics,
        daily_prev_close={"000001.SZ": 10.0},
    )
    # Next bar is one-word limit up at 11.0 (10% up from 10.0)
    next_bar = {"trade_time": "20250106 09:40:00", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "vol": 0, "amount": 0}
    # Place BUY order
    order = Order(ts_code="000001.SZ", side="BUY", shares=100, signal_time="20250106 09:35:00", next_exec_time="20250106 09:40:00")
    # Should not fill due to one-word limit up; engine internal check only in run_day, so mimic check manually
    blocked = eng._one_word_limit("000001.SZ", next_bar, prev_close=10.0, up=True)
    assert blocked is True


def test_fee_consistency():
    tmp_path = Path.cwd() / "results" / "tmp_test_fee"
    tmp_path.mkdir(parents=True, exist_ok=True)
    basics = pd.DataFrame([{"ts_code": "600000.SH", "exchange": "SH", "is_st": False}])
    cost = CostModel(commission_rate=0.0003, transfer_fee=0.00002, stamp_duty=0.001, slippage_bps=0.0, min_commission=5)
    eng = BacktestEngine(
        strategies=[],
        initial_cash=1000000.0,
        cost_model=cost,
        results_dir=tmp_path,
        basics=basics,
        daily_prev_close={"600000.SH": 10.0},
    )
    # BUY 1000 shares at 10.00
    order = Order(ts_code="600000.SH", side="BUY", shares=1000, signal_time="20250106 09:35:00", next_exec_time="20250106 09:40:00")
    filled = eng._exec_order(order, bar_open=10.0, trade_time="20250106 09:40:00")
    assert filled
    # SELL 1000 at 10.50
    order2 = Order(ts_code="600000.SH", side="SELL", shares=1000, signal_time="20250107 09:35:00", next_exec_time="20250107 09:40:00")
    filled2 = eng._exec_order(order2, bar_open=10.5, trade_time="20250107 09:40:00")
    assert filled2
    # Last trade is SELL, check fee math
    last = eng.trades[-1]
    amount = 10.5 * 1000
    commission = max(5, amount * 0.0003)
    transfer = amount * 0.00002  # SH only
    stamp = amount * 0.001
    expect_fee = commission + transfer + stamp
    assert abs(last["fee"] - expect_fee) < 1e-6


def test_limit_pending_count_in_run_day():
    class BuyFirstBarStrategy(Strategy):
        def __init__(self):
            super().__init__(name="test", params={})
        def on_bar(self, trade_time: str, bar_slice):
            # Buy at first bar close
            if trade_time.endswith("09:35:00"):
                return [OrderIntent("000001.SZ", "BUY", 100, reason="test")]
            return []

    basics = pd.DataFrame([{"ts_code": "000001.SZ", "exchange": "SZ", "is_st": False}])
    eng = BacktestEngine(
        strategies=[BuyFirstBarStrategy()],
        initial_cash=100000.0,
        cost_model=CostModel(min_commission=0),
        results_dir=Path.cwd() / "results" / "tmp_test_limit2",
        basics=basics,
        daily_prev_close={"000001.SZ": 10.0},
    )
    # 09:40 is one-word limit up
    bars = {
        "000001.SZ": [
            {"trade_time": "20250106 09:35:00", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
            {"trade_time": "20250106 09:40:00", "open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0, "vol": 0, "amount": 0},
        ]
    }
    out = eng.run_day("20250106", bars, universe=["000001.SZ"])
    assert out["buy_fail"] >= 1
