# 简介：策略 s12 - 锚定 VWAP（AVWAP）相关的均值与支撑阻力博弈，强调结构靠近成交重心。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class Setup:
    idx: int
    note: str


def _avwap(df: pd.DataFrame) -> pd.Series:
    # anchored vwap at 20d low as proxy
    low20_idx = df["low"].rolling(20).apply(lambda x: x.argmin(), raw=True)
    # compute simple cumulative vwap starting from low20 anchor each day (approximate)
    price = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].astype(float)
    cum_pv = (price * vol).cumsum()
    cum_v = vol.cumsum().replace(0, 1e-12)
    return cum_pv / cum_v


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    avwap = _avwap(df)
    mask = (df["close"] > avwap) & (df["open"] < avwap)
    return [Setup(int(i), "AVWAP回收") for i in df.index[mask.fillna(False)]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    avwap = float(_avwap(df).iloc[setup.idx])
    return {"S1": avwap * 0.99, "S2": avwap, "R1": avwap * 1.02, "R2": avwap * 1.03, "anchors": avwap}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {"window_A_text": "回收AVWAP后不破且承接改善", "window_B_text": "收盘确认站稳AVWAP上方"}


def invalidation(setup: Setup) -> List[str]:
    return ["跌破AVWAP并放量"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    avwap = _avwap(df)
    mask = (df["close"] > avwap) & (df["open"] < avwap)
    return event_study_from_mask(df, mask)
