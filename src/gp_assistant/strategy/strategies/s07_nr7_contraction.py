# 简介：策略 s07 - NR7 最小实体收缩形态，博弈收缩后的突破/趋势延续。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    tr = (df["high"] - df["low"]).abs()
    mask = tr == tr.rolling(7).min()
    return [Setup(int(i), "NR7 收缩") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    return {
        "S1": float(win["low"].min()),
        "S2": float(win["close"].mean()),
        "R1": float(win["high"].max()),
        "R2": float(win["high"].max()) * 1.02,
        "anchors": float(win["close"].mean()),
    }


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "收缩后首次回收不破低点；量能温和",
        "window_B_text": "收盘站稳关键结构；不追价",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["放量跌破收缩低点"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    tr = (df["high"] - df["low"]).abs()
    mask = tr == tr.rolling(7).min()
    return event_study_from_mask(df, mask)
