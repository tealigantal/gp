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
    # Breakout confirmation, then a 1-5 bar pullback that closes back above
    # breakout/MA supports. This makes S6 a tail-confirmed second-entry setup.
    if df is None or len(df) < 25:
        return []
    x = df.copy()
    high20 = x["high"].rolling(20).max()
    ma10 = x["ma10"] if "ma10" in x.columns else x["close"].rolling(10).mean()
    ma20 = x["ma20"] if "ma20" in x.columns else x["close"].rolling(20).mean()
    vol20 = x["volume"].rolling(20).mean() if "volume" in x.columns else pd.Series(0.0, index=x.index)
    breakout_level = high20.shift(1)
    breakout = x["close"] > breakout_level
    idxs: List[int] = []
    for i in range(len(x)):
        if not bool(breakout.iloc[i]):
            continue
        level = float(breakout_level.iloc[i]) if pd.notna(breakout_level.iloc[i]) else 0.0
        if level <= 0:
            continue
        breakout_close = float(x["close"].iloc[i])
        for j in range(1, 6):
            k = i + j
            if k >= len(x):
                break
            close_k = float(x["close"].iloc[k])
            low_k = float(x["low"].iloc[k])
            ma10_k = float(ma10.iloc[k]) if pd.notna(ma10.iloc[k]) else 0.0
            ma20_k = float(ma20.iloc[k]) if pd.notna(ma20.iloc[k]) else 0.0
            support = max(level, ma10_k, ma20_k)
            stop = max(level * 0.97, min(v for v in [ma10_k, ma20_k] if v > 0) * 0.98 if (ma10_k > 0 and ma20_k > 0) else level * 0.97)
            pulled_back = low_k <= level * 1.025 and close_k <= breakout_close * 1.08
            recovered = support > 0 and close_k >= support
            not_broken = low_k >= stop * 0.985 and close_k >= stop
            volume_ok = True
            try:
                v_now = float(x["volume"].iloc[k])
                v_ref = float(vol20.iloc[k]) if pd.notna(vol20.iloc[k]) else 0.0
                red_bar = close_k < float(x["open"].iloc[k])
                volume_ok = (not red_bar) or v_ref <= 0 or v_now <= v_ref * 1.8
            except Exception:
                volume_ok = True
            if pulled_back and recovered and not_broken and volume_ok:
                idxs.append(k)
                break
    return [Setup(int(i), "突破确认后的尾盘二买") for i in sorted(set(idxs))]


def key_bands(df: pd.DataFrame, setup: Setup) -> Dict[str, float]:
    win = df.iloc[max(0, setup.idx - 20) : setup.idx + 1]
    ma10 = df["ma10"] if "ma10" in df.columns else df["close"].rolling(10).mean()
    ma20 = df["ma20"] if "ma20" in df.columns else df["close"].rolling(20).mean()
    close_now = float(df["close"].iloc[setup.idx])
    support = max(
        float(win["close"].quantile(0.65)),
        float(ma10.iloc[setup.idx]) if pd.notna(ma10.iloc[setup.idx]) else 0.0,
        float(ma20.iloc[setup.idx]) if pd.notna(ma20.iloc[setup.idx]) else 0.0,
    )
    support = min(support, close_now * 0.995)
    return {
        "S1": support,
        "S2": max(support, float(win["close"].quantile(0.5))),
        "R1": float(win["close"].quantile(0.8)),
        "R2": float(win["close"].quantile(0.9)),
        "anchors": support,
    }


def confirm_text(setup: Setup, q_grade: str) -> Dict[str, str]:
    return {
        "window_A_text": "回踩关键带不破并回收；不追涨不打板",
        "window_B_text": "收盘确认不破支撑带上沿；结构成立再评估隔夜",
    }


def invalidation(setup: Setup) -> List[str]:
    return ["尾盘跌破突破位/MA10/MA20支撑", "放量回落且未收回支撑"]


def event_study(df: pd.DataFrame, setups: List[Setup]):
    from ..event_study import event_study_from_mask
    idxs = [int(s.idx) for s in detect_setups(df)]
    mask = pd.Series(False, index=df.index)
    for idx in idxs:
        if 0 <= idx < len(mask):
            mask.iloc[idx] = True
    return event_study_from_mask(df, mask)
