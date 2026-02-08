import pandas as pd
import numpy as np

from gp_assistant.tools.backtest import StrategyDef, run_event_backtest


def make_feat_with_event():
    n = 25
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series([10 + i for i in range(n)], dtype=float)
    # inject a dip after the entry day (t+2) to test MDD window
    close.iloc[7] = close.iloc[6] - 1.0  # entry at 6, dip at 7
    df = pd.DataFrame({
        "date": dates,
        "open": close - 0.2,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": np.linspace(1e5, 2e5, n),
        "amount": np.linspace(1e5, 2e5, n) * close,
    })
    df["bias6_cross_up"] = False
    df.loc[5, "bias6_cross_up"] = True  # event at t=5
    df.attrs["symbol"] = "000001.SZ"
    return df


def test_backtest_k_win_mdd():
    df = make_feat_with_event()
    strat = StrategyDef(id="S1", name="Bias6 CrossUp", forward_days=[2, 5, 10], min_samples=1, event_rule={"name": "bias6_cross_up", "params": {}})
    stats = run_event_backtest(df, strat)
    assert stats.k == 1
    assert abs(stats.win_rate_2 - 1.0) < 1e-9
    assert abs(stats.win_rate_5 - 1.0) < 1e-9
    assert abs(stats.win_rate_10 - 1.0) < 1e-9
    # entry t+1 at index 6, close=16
    r2 = df.loc[6 + 2, "close"] / df.loc[6, "close"] - 1.0
    r5 = df.loc[6 + 5, "close"] / df.loc[6, "close"] - 1.0
    r10 = df.loc[6 + 10, "close"] / df.loc[6, "close"] - 1.0
    assert abs(stats.avg_return_2 - r2) < 1e-9
    assert abs(stats.avg_return_5 - r5) < 1e-9
    assert abs(stats.avg_return_10 - r10) < 1e-9
    # Expected MDD over next 10 days from entry: min(close/entry)-1, includes the dip at index 7
    entry = df.loc[6, "close"]
    future = df.loc[6:6+10, "close"] / entry
    exp_mdd = float(future.min() - 1.0)
    assert abs(stats.mdd10_avg - exp_mdd) < 1e-12
