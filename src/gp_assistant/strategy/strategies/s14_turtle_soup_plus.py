# 简介：策略 s14 - 海龟汤增强版（Turtle Soup Plus），结合更严格的反包/确认规则。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    # Turtle Soup+1: false breakout above N-day high then close back below
    high20 = df["high"].rolling(20).max()
    mask = (df["high"] > high20.shift(1)) & (df["close"] < high20.shift(1))
    return [Setup(int(i), "TurtleSoup+ 上方假破") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    low = float(win["low"].min())
    high = float(win["high"].max())
    mid = float(win["close"].mean())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {"window_A_text": "假破回落后等待回踩确认，不追价", "window_B_text": "收盘前确认不破关键结构"}


def invalidation(setup: Setup) -> List[str]:
    return ["再次冲高回落且放量"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    high20 = df["high"].rolling(20).max()
    mask = (df["high"] > high20.shift(1)) & (df["close"] < high20.shift(1))
    return event_study_from_mask(df, mask)
