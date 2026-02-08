# 简介：技术指标库。计算均线、BIAS 交叉、RSI2、BB宽度、NR7、量比、ATR%、Gap% 等
# 指标，为策略与评分提供特征输入。
from __future__ import annotations

from typing import Any, Dict, Tuple
import numpy as np
import pandas as pd


def ensure_amount(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    meta: Dict[str, Any] = {}
    x = df.copy()
    if "amount" not in x.columns:
        vwap = (x["high"] + x["low"] + x["close"]) / 3.0
        x["amount"] = vwap * x["volume"].astype(float)
        meta["amount_estimated"] = True
    else:
        x["amount"] = pd.to_numeric(x["amount"], errors="coerce")
        if x["amount"].isna().any():
            vwap = (x["high"] + x["low"] + x["close"]) / 3.0
            x["amount"] = x["amount"].fillna(vwap * x["volume"].astype(float))
            meta["amount_estimated"] = True
        else:
            meta["amount_estimated"] = False
    return x, meta


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat([(df["high"] - df["low"]).abs(), (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1)
    return ranges.max(axis=1)


def wilder_rma(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1.0 / float(n), adjust=False).mean()


def atr_wilder(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return wilder_rma(true_range(df), n)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    x, _ = ensure_amount(df)
    x = x.copy()
    # Moving averages (include windows used by downstream features)
    for w in [5, 6, 10, 12, 20, 24, 60]:
        x[f"ma{w}"] = x["close"].rolling(w).mean()
    # Slope20
    ma20 = x["ma20"]
    ma20_5 = ma20.shift(5)
    x["slope20"] = (ma20 - ma20_5) / ma20_5.replace(0, np.nan)
    # BIAS and crosses
    def bias_for(w: int) -> pd.Series:
        ma = x[f"ma{w}"]
        return (x["close"] - ma) / ma.replace(0, np.nan)

    x["bias6"] = bias_for(6)
    x["bias12"] = bias_for(12)
    x["bias24"] = bias_for(24)
    b6, b12 = x["bias6"], x["bias12"]
    x["bias6_cross_up"] = (b6.shift(1) <= b12.shift(1)) & (b6 > b12)
    x["bias6_cross_down"] = (b6.shift(1) >= b12.shift(1)) & (b6 < b12)
    # Simplified divergence proxy: bias diff widening while price near lows
    x["divergence20"] = (b6 - b12).rolling(20).mean() > 0
    # RSI2 (Wilder)
    delta = x["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = wilder_rma(gain, 2)
    avg_loss = wilder_rma(loss, 2)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    x["rsi2"] = 100.0 - (100.0 / (1.0 + rs))
    # BBWidth(20,2)
    mid = x["close"].rolling(20).mean()
    std = x["close"].rolling(20).std(ddof=0)
    upper, lower = mid + 2 * std, mid - 2 * std
    x["bbwidth20"] = (upper - lower) / mid.replace(0, np.nan)
    # NR7
    tr = true_range(x)
    x["nr7"] = tr == tr.rolling(7).min()
    # Volume ratio
    x["volratio10"] = x["volume"] / x["volume"].rolling(10).mean().replace(0, np.nan)
    # ATR% and Gap%
    x["atr14"] = atr_wilder(x, 14)
    x["atr_pct"] = x["atr14"] / x["close"].replace(0, np.nan)
    prev_close = x["close"].shift(1)
    x["gap_pct"] = (x["open"] - prev_close) / prev_close.replace(0, np.nan)
    # Amount 5d
    x["amount_5d_avg"] = x["amount"].rolling(5).mean()
    return x
