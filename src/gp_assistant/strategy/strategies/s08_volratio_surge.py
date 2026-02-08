# 简介：策略 s08 - 量比放大与价量配合的动量型信号，关注放量不跌与承接质量。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    if "volratio10" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["volratio10"] > 1.5
    return [Setup(int(i), "量能放大") for i in df.index[mask.fillna(False)]]


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
        "window_A_text": "放量后回踩不破关键带；承接良好",
        "window_B_text": "收盘确认不破关键带上沿；避免追高",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["放量不涨"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    if "volratio10" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["volratio10"] > 1.5
    return event_study_from_mask(df, mask)
