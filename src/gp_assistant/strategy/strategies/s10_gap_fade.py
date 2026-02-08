# 简介：策略 s10 - 缺口回补/高开回落等 Gap 衰退博弈，强调不追涨与风险控制。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    prev_close = df["close"].shift(1)
    gap_pct = (df["open"] - prev_close) / prev_close.replace(0, 1e-12)
    mask = gap_pct > 0.02
    # Strategy: gap up then fade; only for observation per rules
    return [Setup(int(i), "高开>2%观察") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 10) : setup.idx + 1]
    low = float(win["low"].min())
    mid = float(win["close"].mean())
    high = float(win["high"].max())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "当日禁买，仅观察结构变化",
        "window_B_text": "仅观察，不执行；等待后续回踩确认",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["追高冲动"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    prev_close = df["close"].shift(1)
    gap_pct = (df["open"] - prev_close) / prev_close.replace(0, 1e-12)
    mask = gap_pct > 0.02
    return event_study_from_mask(df, mask)
