# 简介：策略 s05 - MA20 回撤与再上行的结构性买点，强调不追高、回踩确认。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    ma20 = df["close"].rolling(20).mean()
    cond = (ma20 > ma20.shift(5)) & (df["low"] <= ma20) & (df["close"] >= ma20)
    return [Setup(int(i), "MA20回踩确认") for i in df.index[cond.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    ma20 = float(df["close"].rolling(20).mean().iloc[setup.idx])
    return {"S1": ma20 * 0.99, "S2": ma20, "R1": ma20 * 1.02, "R2": ma20 * 1.03, "anchors": ma20}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "回踩MA20后快速回收且低点不破；量能缩而不弱",
        "window_B_text": "收盘站稳MA20上方且不回落破位；不追价",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["跌破MA20且放量", "连续阴跌"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    ma20 = df["close"].rolling(20).mean()
    cond = (ma20 > ma20.shift(5)) & (df["low"] <= ma20) & (df["close"] >= ma20)
    return event_study_from_mask(df, cond)
