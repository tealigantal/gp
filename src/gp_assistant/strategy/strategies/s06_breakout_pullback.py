# 简介：策略 s06 - 突破后回踩确认的趋势延续形态，强调结构稳定与承接。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    # recent breakout (close > 20d high), then 1-3 day pullback not losing structure
    high20 = df["high"].rolling(20).max()
    breakout = df["close"] > high20.shift(1)
    pullback = (df["close"] < df["close"].shift(1))
    idxs = []
    for i in range(len(df)):
        if breakout.iloc[i]:
            for j in range(1, 4):
                if i + j < len(df) and pullback.iloc[i + j]:
                    idxs.append(i + j)
                    break
    return [Setup(int(i), "突破后二买回踩") for i in idxs]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    return {
        "S1": float(win["close"].quantile(0.3)),
        "S2": float(win["close"].quantile(0.5)),
        "R1": float(win["close"].quantile(0.8)),
        "R2": float(win["close"].quantile(0.9)),
        "anchors": float(win["close"].mean()),
    }


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "回踩关键带不破并回收；不追涨不打板",
        "window_B_text": "收盘确认不破支撑带上沿；结构成立再评估隔夜",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["跌破回踩带", "放量回落"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    high20 = df["high"].rolling(20).max()
    breakout = df["close"] > high20.shift(1)
    # mark pullback days simply as next day of breakout
    mask = breakout.shift(1).fillna(False)
    return event_study_from_mask(df, mask)
