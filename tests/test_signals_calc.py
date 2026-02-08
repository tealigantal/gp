import numpy as np
import pandas as pd

from gp_assistant.tools.signals import compute_indicators


def make_norm_df(n=30):
    # Build a simple upward series with small noise
    rng = pd.date_range("2024-01-01", periods=n, freq="D")
    close = pd.Series(np.linspace(10, 20, n))
    open_ = close - 0.2
    high = close + 0.5
    low = close - 0.5
    vol = pd.Series(np.linspace(1e5, 2e5, n))
    amount = vol * close
    df = pd.DataFrame({
        "date": rng,
        "open": open_.values,
        "high": high.values,
        "low": low.values,
        "close": close.values,
        "volume": vol.values,
        "amount": amount.values,
    })
    return df


def test_amount_5d_avg():
    df = make_norm_df(10)
    out = compute_indicators(df, None)
    # Check last value equals rolling mean of last 5 amounts
    expected = df["amount"].rolling(5).mean().iloc[-1]
    assert abs(out["amount_5d_avg"].iloc[-1] - expected) < 1e-6


def test_bias_calculation():
    df = make_norm_df(30)
    out = compute_indicators(df, None)
    # For last row, compute bias6 manually
    ma6 = df["close"].rolling(6).mean().iloc[-1]
    bias6 = (df["close"].iloc[-1] - ma6) / ma6
    assert abs(out["bias6"].iloc[-1] - bias6) < 1e-12


def test_rsi2_against_reference():
    df = make_norm_df(20)
    out = compute_indicators(df, {"rsi_period": 2})
    # Build reference RSI(2) using Wilder smoothing
    close = df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/2, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/2, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    rsi = 100 - (100 / (1 + rs))
    assert abs(out["rsi2"].iloc[-1] - rsi.iloc[-1]) < 1e-9


def test_atr_wilder_against_reference():
    df = make_norm_df(25)
    out = compute_indicators(df, {"atr_period": 14})
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_ref = tr.ewm(alpha=1/14, adjust=False).mean()
    assert abs(out["atr14"].iloc[-1] - atr_ref.iloc[-1]) < 1e-9
