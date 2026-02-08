# 简介：工具 - 生成或检视信号（如 bias 交叉、NR7 等），便于脚本化验证。
from __future__ import annotations

from typing import Any, List, Dict
import pandas as pd

from ..core.types import ToolResult


def _ma(df: pd.DataFrame, n: int) -> pd.Series:
    return df["close"].rolling(n).mean()


def run_signals(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    """Compute simple signal on a price series.

    Args expects: df (DataFrame)
    """
    df = args.get("df")
    if df is None or not isinstance(df, pd.DataFrame):
        return ToolResult(ok=False, message="缺少或无效的 df 数据")
    if len(df) < 3:
        return ToolResult(ok=True, message="数据太短，无法计算", data={"signals": []})

    df = df.copy()
    try:
        df["ma5"] = _ma(df, 5)
        df["ma10"] = _ma(df, 10)
        cross = (
            (df["ma5"].shift(1) <= df["ma10"].shift(1)) & (df["ma5"] > df["ma10"])  # type: ignore[operator]
        )
        idx = df.index[cross.fillna(False)]
        dates: List[str] = []
        if "date" in df.columns:
            dates = [str(df.loc[i, "date"]) for i in idx]
        return ToolResult(ok=True, message=f"检测到 {len(dates)} 次金叉", data={"golden_cross_dates": dates})
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, message=f"信号计算失败: {e}")


# ---------------- Deterministic indicator engine -----------------
def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            (df["high"] - df["low"]).abs(),
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _wilder_rma(x: pd.Series, n: int) -> pd.Series:
    return x.ewm(alpha=1.0 / float(n), adjust=False).mean()


def _atr_wilder(df: pd.DataFrame, n: int) -> pd.Series:
    tr = _true_range(df)
    return _wilder_rma(tr, n)


def _rsi_wilder(close: pd.Series, n: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _wilder_rma(gain, n)
    avg_loss = _wilder_rma(loss, n)
    rs = avg_gain / avg_loss.replace(0, 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def compute_indicators(df_norm: pd.DataFrame, config: Dict[str, Any] | None = None) -> pd.DataFrame:  # noqa: ANN401
    """Compute deterministic indicators on normalized OHLCV.

    Required columns: date, open, high, low, close, volume, amount
    Returns df with added columns as specified.
    """
    cfg = config or {}
    ma_wins = cfg.get("ma_windows", [5, 10, 20, 60])
    atr_n = int(cfg.get("atr_period", 14))
    rsi_n = int(cfg.get("rsi_period", 2))
    bb_n = int(cfg.get("bb_window", 20))
    volratio_n = int(cfg.get("volratio_window", 10))

    df = df_norm.copy()
    need = ["date", "open", "high", "low", "close", "volume", "amount"]
    miss = [c for c in need if c not in df.columns]
    if miss:
        raise ValueError(f"缺少必要列: {miss}")

    # Rolling indicators
    # amount_5d_avg
    df["amount_5d_avg"] = df["amount"].rolling(5).mean()

    # MA windows
    for w in ma_wins:
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    # Ensure MA for bias windows exist
    for w in (6, 12, 24):
        if f"ma{w}" not in df.columns:
            df[f"ma{w}"] = df["close"].rolling(w).mean()

    # ATR and ATR percentage
    df[f"atr{atr_n}"] = _atr_wilder(df, atr_n)
    df["atr14"] = df[f"atr{atr_n}"] if atr_n == 14 else df[f"atr{atr_n}"] * 1.0  # alias
    df["atr_pct"] = df["atr14"] / df["close"].replace(0, 1e-12)

    # BIAS metrics
    def bias_for(w: int) -> pd.Series:
        ma = df[f"ma{w}"]
        return (df["close"] - ma) / ma.replace(0, 1e-12)

    df["bias6"] = bias_for(6)
    df["bias12"] = bias_for(12)
    df["bias24"] = bias_for(24)

    b6 = df["bias6"]
    b12 = df["bias12"]
    df["bias6_cross_up"] = (b6.shift(1) <= b12.shift(1)) & (b6 > b12)
    df["bias6_cross_down"] = (b6.shift(1) >= b12.shift(1)) & (b6 < b12)

    # RSI2
    df["rsi2"] = _rsi_wilder(df["close"], rsi_n)

    # Bollinger band width on middle band
    mid = df["close"].rolling(bb_n).mean()
    std = df["close"].rolling(bb_n).std(ddof=0)
    upper = mid + 2 * std
    lower = mid - 2 * std
    bbwidth = (upper - lower) / mid.replace(0, 1e-12)
    df["bbwidth20"] = bbwidth

    # NR7 event: 7-day true range minimal event
    tr = _true_range(df)
    rolling_min = tr.rolling(7).min()
    df["nr7"] = tr == rolling_min

    # Volume ratio
    df["volratio10"] = df["volume"] / df["volume"].rolling(volratio_n).mean().replace(0, 1e-12)

    # insufficient history flag
    need_len = max([60] + ma_wins + [atr_n, bb_n, volratio_n, 24])
    df["insufficient_history"] = len(df) < need_len

    return df
