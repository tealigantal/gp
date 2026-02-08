# 简介：时间序列交叉验证（Purged Walk-Forward）。在时间轴上避免泄漏的
# 交叉验证评估，用于策略稳健性与期望统计的估计。
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd


@dataclass
class CVStats:
    k: int
    win_rate_5d_mean: float
    win_rate_5d_std: float
    mean_return_5d_mean: float
    mean_return_5d_std: float
    drawdown_proxy_mean: float


def purged_walk_forward(df: pd.DataFrame, k_folds: int = 5, gap: int = 5) -> CVStats:
    """Time-series CV without leakage.

    For simplicity, use rolling 5-day forward return of close as target.
    """
    n = len(df)
    if n < 60:
        return CVStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    fold_size = n // k_folds
    wrs: List[float] = []
    means: List[float] = []
    dds: List[float] = []
    for i in range(k_folds):
        start = i * fold_size
        end = (i + 1) * fold_size
        # purge gap forward/backward
        tr_start = start + gap
        tr_end = end - gap
        if tr_end - tr_start <= 10:
            continue
        closes = df["close"].astype(float).values
        # compute 5-day forward returns within train window as proxy
        seg = closes[tr_start:tr_end]
        if len(seg) < 10:
            continue
        fwd = seg[5:] / seg[:-5] - 1.0
        if len(fwd) == 0:
            continue
        wr = float((fwd > 0).sum() / len(fwd))
        m = float(fwd.mean())
        # drawdown proxy in window
        window = seg
        dd = float((window / np.maximum.accumulate(window)).min() - 1.0)
        wrs.append(wr)
        means.append(m)
        dds.append(dd)
    if not wrs:
        return CVStats(0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return CVStats(
        k=len(wrs),
        win_rate_5d_mean=float(np.mean(wrs)),
        win_rate_5d_std=float(np.std(wrs)),
        mean_return_5d_mean=float(np.mean(means)),
        mean_return_5d_std=float(np.std(means)),
        drawdown_proxy_mean=float(np.mean(dds)),
    )
