# 简介：策略 s09 - 筹码支撑与成本带回收，利用低吸与支撑确认的结构性机会。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd

from ..chip_model import compute_chip


@dataclass
class Setup:
    idx: int
    note: str


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    # Use chip 90% low as support proxy; detect days near that band
    chip, _ = compute_chip(df)
    s1 = chip.band_90_low
    mask = (df["low"] <= s1) & (df["close"] >= s1)
    return [Setup(int(i), "筹码带支撑回收") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    chip, _ = compute_chip(df.iloc[: setup.idx + 1])
    return {"S1": chip.band_90_low, "S2": chip.avg_cost, "R1": chip.band_90_high, "R2": chip.band_90_high * 1.02, "anchors": chip.avg_cost}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "贴近筹码带低位后快速回收，低点抬高；量能不失控",
        "window_B_text": "收盘确认站稳S2；不满足则观望",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["跌破筹码带且不回收"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    chip, _ = compute_chip(df)
    s1 = chip.band_90_low
    mask = (df["low"] <= s1) & (df["close"] >= s1)
    return event_study_from_mask(df, mask)
