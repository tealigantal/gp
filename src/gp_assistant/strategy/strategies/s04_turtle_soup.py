# 简介：策略 s04 - 海龟汤（Turtle Soup）反转形态，围绕假突破后的反包机会。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    # Turtle Soup: false breakdown below N-day low (use 20)
    low20 = df["low"].rolling(20).min()
    prev_low20 = low20.shift(1)
    mask = (df["low"] < prev_low20) & (df["close"] > prev_low20)
    return [Setup(int(i), "TurtleSoup 20d 假破") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    low = float(win["low"].min())
    high = float(win["high"].max())
    mid = float(win["close"].mean())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "假破后快速回收关键带；不再创新低；量能不失控",
        "window_B_text": "收盘确认站稳关键结构；次日评估是否隔夜",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["再创新低", "放量下破"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    low20 = df["low"].rolling(20).min()
    prev_low20 = low20.shift(1)
    mask = (df["low"] < prev_low20) & (df["close"] > prev_low20)
    return event_study_from_mask(df, mask)
