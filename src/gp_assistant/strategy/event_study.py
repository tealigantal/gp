# 简介：事件研究。基于给定掩码统计事件前后窗口的收益/胜率/回撤等，
# 为策略解释与打分提供统计参考。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
import pandas as pd


@dataclass
class EventStats:
    k: int
    win_rate_2: float
    win_rate_5: float
    win_rate_10: float
    mean_return_2: float
    mean_return_5: float
    mean_return_10: float
    mdd10_proxy: float
    sample_warning: bool


def _forward_metrics(df: pd.DataFrame, idxs: List[int]) -> EventStats:
    f2, f5, f10 = [], [], []
    mdds = []
    for i in idxs:
        if i + 1 >= len(df):
            continue
        entry = float(df.loc[i + 1, "close"])  # next-day close
        # horizon limited by data length
        t2 = i + 2
        t5 = i + 5
        t10 = i + 10
        if t2 < len(df):
            f2.append(float(df.loc[t2, "close"]) / entry - 1.0)
        if t5 < len(df):
            f5.append(float(df.loc[t5, "close"]) / entry - 1.0)
        if t10 < len(df):
            f10.append(float(df.loc[t10, "close"]) / entry - 1.0)
        # MDD proxy within 10d
        tN = min(len(df) - 1, i + 10)
        window = df.loc[i + 1 : tN, "close"].astype(float)
        mdd = float((window / entry).min() - 1.0)
        mdds.append(mdd)
    k = min(len(f2), len(f5), len(f10))
    def wr(a: List[float]) -> float:
        return float(sum(1 for x in a if x > 0) / len(a)) if a else 0.0
    return EventStats(
        k=k,
        win_rate_2=wr(f2),
        win_rate_5=wr(f5),
        win_rate_10=wr(f10),
        mean_return_2=float(pd.Series(f2).mean() if f2 else 0.0),
        mean_return_5=float(pd.Series(f5).mean() if f5 else 0.0),
        mean_return_10=float(pd.Series(f10).mean() if f10 else 0.0),
        mdd10_proxy=float(pd.Series(mdds).mean() if mdds else 0.0),
        sample_warning=bool(k < 5),
    )


def event_study_from_mask(df_feat: pd.DataFrame, mask: pd.Series) -> EventStats:
    idxs = list(df_feat.index[mask.fillna(False)])
    return _forward_metrics(df_feat, idxs)
