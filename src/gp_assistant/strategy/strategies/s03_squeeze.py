# 简介：策略 s03 - 波动收缩（Squeeze）形态，博弈收缩后的方向性释放。
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
    thr = float(bbw.rolling(60).quantile(0.2).iloc[-1]) if len(df) >= 60 else float(bbw.quantile(0.2))
    mask = bbw < thr
    return [Setup(int(i), "波动压缩Squeeze") for i in df.index[mask]]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 60) : setup.idx + 1]
    low = float(win["close"].quantile(0.2))
    high = float(win["close"].quantile(0.8))
    mid = float(win["close"].mean())
    return {"S1": low, "S2": mid, "R1": high, "R2": high * 1.03, "anchors": mid}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "压缩后首次回收关键带且不再创新低，量能温和；满足≥2项",
        "window_B_text": "收盘突破中轨并站稳；不追价，确认后次日评估",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["持续阴跌", "放量跌破关键带"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    if "bbwidth20" not in df.columns:
        from ..indicators import compute_indicators
        df = compute_indicators(df)
    bbw = df["bbwidth20"]
    thr = float(bbw.rolling(60).quantile(0.2).iloc[-1]) if len(df) >= 60 else float(bbw.quantile(0.2))
    mask = bbw < thr
    return event_study_from_mask(df, mask)
