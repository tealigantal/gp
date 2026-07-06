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
    if df is None or len(df) == 0:
        return pd.Series(dtype="float64")
    price = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0).astype(float)
    pv = (price * vol).fillna(0.0)
    high20 = df["high"].rolling(20).max().shift(1)
    vol20 = vol.rolling(20).mean()
    volume_breakout = (df["close"] > high20) & (vol >= vol20 * 1.5)
    out = []
    for i in range(len(df)):
        anchors = []
        lo20_start = max(0, i - 19)
        lo60_start = max(0, i - 59)
        try:
            low20 = df["low"].iloc[lo20_start : i + 1].astype(float)
            anchors.append(lo20_start + int(low20.to_numpy().argmin()))
        except Exception:
            anchors.append(lo20_start)
        try:
            low60 = df["low"].iloc[lo60_start : i + 1].astype(float)
            anchors.append(lo60_start + int(low60.to_numpy().argmin()))
        except Exception:
            anchors.append(lo60_start)
        try:
            breakout_window = volume_breakout.iloc[lo60_start : i + 1]
            if bool(breakout_window.any()):
                true_positions = [pos for pos, flag in enumerate(breakout_window.tolist()) if bool(flag)]
                anchors.append(lo60_start + int(true_positions[-1]))
        except Exception:
            pass
        anchor = max(0, min(i, max(anchors)))
        v = float(vol.iloc[anchor : i + 1].sum())
        if v <= 0:
            out.append(float(price.iloc[i]))
        else:
            out.append(float(pv.iloc[anchor : i + 1].sum() / v))
    return pd.Series(out, index=df.index)


def detect_setups(df: pd.DataFrame) -> List[Setup]:
    avwap = _avwap(df)
    if avwap.empty:
        return []
    close = pd.to_numeric(df["close"], errors="coerce")
    open_ = pd.to_numeric(df["open"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    reclaim = (close > avwap) & ((close.shift(1) <= avwap.shift(1)) | (open_ <= avwap))
    deviation = (close - avwap) / avwap.replace(0, pd.NA)
    near_anchor = deviation.between(0.0, 0.055, inclusive="both")
    support_held = low >= avwap * 0.97
    mask = reclaim & near_anchor & support_held
    return [Setup(int(i), "真实AVWAP回收") for i, ok in enumerate(mask.fillna(False).tolist()) if bool(ok)]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    avwap = float(_avwap(df).iloc[setup.idx])
    return {"S1": avwap * 0.99, "S2": avwap, "R1": avwap * 1.02, "R2": avwap * 1.03, "anchors": avwap}


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {"window_A_text": "回收真实AVWAP后不追高，观察承接", "window_B_text": "尾盘站稳AVWAP且偏离不大"}


def invalidation(setup: Setup) -> List[str]:
    return ["尾盘跌破AVWAP", "站回后偏离过大或放量回落"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    avwap = _avwap(df)
    mask = (df["close"] > avwap) & (df["open"] < avwap)
    return event_study_from_mask(df, mask)
