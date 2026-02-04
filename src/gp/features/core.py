from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, List

import pandas as pd

from ..datapool import DataPool


def rsi(series: pd.Series, n: int = 2) -> pd.Series:
    delta = series.diff()
    gain = (delta.clip(lower=0)).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / (loss.replace(0, 1e-12))
    return 100 - (100 / (1 + rs))


def rolling_slope(series: pd.Series, window: int = 20) -> pd.Series:
    # Simple slope via linear regression on index
    x = pd.Series(range(len(series)), index=series.index)
    def _s(sub: pd.Series):
        if sub.isna().any():
            return float('nan')
        xx = x.loc[sub.index]
        xm = xx.mean(); ym = sub.mean()
        cov = ((xx - xm) * (sub - ym)).sum()
        var = ((xx - xm) ** 2).sum()
        return cov / (var if var != 0 else 1)
    return series.rolling(window).apply(_s, raw=False)


def compute_features_for(dp: DataPool, code: str) -> pd.DataFrame:
    bars = dp.read_bars(code)
    if bars.empty:
        return bars
    df = bars.copy()
    prev_close = df["close"].shift(1)
    high_pc = pd.concat([df["high"], prev_close], axis=1).max(axis=1)
    low_pc = pd.concat([df["low"], prev_close], axis=1).min(axis=1)
    df["tr"] = high_pc - low_pc
    df["atrp"] = (df["tr"].rolling(14).mean() / df["close"]) * 100.0
    df["ma20"] = df["close"].rolling(20).mean()
    for n in (6, 12, 24):
        df[f"bias{n}"] = (df["close"] / df["close"].rolling(n).mean() - 1) * 100.0
    df["rsi2"] = rsi(df["close"], 2)
    # BBWidth (20,2): (upper - lower)/mid
    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    df["bbwidth"] = (upper - lower) / mid
    # NR7: today's range < min of last 6 days range
    rng = df["high"] - df["low"]
    df["nr7"] = rng < rng.shift(1).rolling(6).min()
    # VolRatio: volume / avg volume(20)
    df["volratio"] = df["volume"] / df["volume"].rolling(20).mean()
    df["slope20"] = rolling_slope(df["close"], 20)
    out = df[["date", "code", "atrp", "ma20", "bias6", "bias12", "bias24", "rsi2", "bbwidth", "nr7", "volratio", "slope20"]]
    # Upsert into features_daily
    dp.con.unregister("out") if "out" in [x[0] for x in dp.con.execute("PRAGMA show_tables").fetchall()] else None
    dp.con.register("out", out)
    dp.con.execute("CREATE OR REPLACE TEMP TABLE _f AS SELECT * FROM out")
    dp.con.execute(
        """
        INSERT INTO features_daily
        SELECT * FROM _f f
        WHERE NOT EXISTS (
            SELECT 1 FROM features_daily x WHERE x.code=f.code AND x.date=f.date
        )
        """
    )
    return out


def compute_features_incremental(dp: DataPool, codes: Iterable[str]) -> None:
    for code in codes:
        compute_features_for(dp, code)
