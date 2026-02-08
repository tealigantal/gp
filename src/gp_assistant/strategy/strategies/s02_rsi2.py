# 简介：策略 s02 - RSI2 低位反转/极值回归类短线信号，关注超短反弹机会。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    if "rsi2" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = (df["rsi2"] < 10).astype(bool)
    return [Setup(int(i), "RSI2极度超卖") for i in df.index[mask]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 60) : setup.idx + 1]
    low = float(win["close"].quantile(0.1))
    high = float(win["close"].quantile(0.9))
    mid = float(win["close"].mean())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "低吸仅在关键带回收且分时重心抬高时考虑；否则观望",
        "window_B_text": "尾盘确认不破关键带上沿，收盘站稳后再评估隔夜",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["放量不涨", "高位长上影"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    if "rsi2" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["rsi2"] < 10
    return event_study_from_mask(df, mask)
