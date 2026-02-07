from __future__ import annotations

from typing import Any, List
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

