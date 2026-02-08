# 简介：策略 s01 - BIAS6 上穿 BIAS12 的动量转强信号，提供关键带与确认/失效条件。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    if "bias6_cross_up" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["bias6_cross_up"].astype(bool)
    return [Setup(int(i), "bias6上穿bias12") for i in df.index[mask]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    # Use chip bands proxy by rolling percentiles of close as deterministic bands
    win = df.iloc[max(0, setup.idx - 60) : setup.idx + 1]
    low = float(win["close"].quantile(0.05))
    high = float(win["close"].quantile(0.95))
    mid = float(win["close"].mean())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.02, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "关键带回收且不再创新低；量能不失控；满足≥2项则记录为承接",
        "window_B_text": "收盘前站稳关键结构，回落不破；满足≥2项则视为转强；否则观望",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["放量不涨", "频繁冲高回落", "贴近压力带"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask

    if "bias6_cross_up" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    mask = df["bias6_cross_up"].astype(bool)
    return event_study_from_mask(df, mask)
