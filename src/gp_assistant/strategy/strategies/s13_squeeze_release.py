# 简介：策略 s13 - 收缩后的释放（Squeeze Release）形态，关注放量突破与延续。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    if "bbwidth20" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    bbw = df["bbwidth20"]
    thr = bbw.rolling(60).quantile(0.2)
    release = (bbw > thr) & (df["close"] > df["close"].rolling(5).mean())
    return [Setup(int(i), "压缩后释放") for i in df.index[release.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    return {
        "S1": float(win["close"].quantile(0.4)),
        "S2": float(win["close"].quantile(0.5)),
        "R1": float(win["close"].quantile(0.85)),
        "R2": float(win["close"].quantile(0.9)),
        "anchors": float(win["close"].mean()),
    }


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {"window_A_text": "释放后等待回踩确认，不追价", "window_B_text": "收盘确认不破结构后评估隔夜"}


def invalidation(setup: Setup) -> List[str]:
    return ["释放后放量回落"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    if "bbwidth20" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    bbw = df["bbwidth20"]
    thr = bbw.rolling(60).quantile(0.2)
    release = (bbw > thr) & (df["close"] > df["close"].rolling(5).mean())
    return event_study_from_mask(df, release)
