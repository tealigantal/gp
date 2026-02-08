# 简介：策略 s11 - RSI2 极值扩展信号，相对 s02 更激进的超短反转博弈。
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
    mask = (df["rsi2"] < 5).astype(bool)
    return [Setup(int(i), "RSI2极端超卖") for i in df.index[mask]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 60) : setup.idx + 1]
    return {
        "S1": float(win["close"].quantile(0.15)),
        "S2": float(win["close"].quantile(0.35)),
        "R1": float(win["close"].quantile(0.7)),
        "R2": float(win["close"].quantile(0.85)),
        "anchors": float(win["close"].mean()),
    }


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "极端超卖仅在回收确认后考虑；结构不满足放弃",
        "window_B_text": "收盘确认站稳关键结构；避免抢反弹",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["继续走弱不回收"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    if "rsi2" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["rsi2"] < 5
    return event_study_from_mask(df, mask)
