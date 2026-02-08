# 简介：风险 - 噪声等级 Q 的评估与辅助（占位/轻实现），用于限制窗口与仓位。
from __future__ import annotations

from typing import Literal
import numpy as np
import pandas as pd


def grade_noise(df_feat: pd.DataFrame, env_grade: Literal["A","B","C","D"]) -> str:
    """Compute Q0-Q3 noise grade from recent stats and env.

    Heuristics:
    - base score from ATR%, BBWidth20, NR7 rarity, vol spikes
    - env C/D: upgrade by one level (capped at Q3)
    """
    tail = df_feat.tail(20)
    atrp = float(tail["atr_pct"].mean()) if len(tail) else 0.0
    bbw = float(tail["bbwidth20"].mean()) if len(tail) else 0.0
    nr7_rate = 1.0 - float(tail["nr7"].mean()) if "nr7" in tail.columns else 1.0
    volratio = float(tail["volratio10"].mean()) if "volratio10" in tail.columns else 1.0
    # simple score
    score = atrp * 4 + bbw * 2 + nr7_rate * 0.5 + max(0.0, volratio - 1.0) * 0.5
    if score < 0.05:
        q = "Q0"
    elif score < 0.10:
        q = "Q1"
    elif score < 0.16:
        q = "Q2"
    else:
        q = "Q3"
    if env_grade in {"C", "D"}:
        order = ["Q0", "Q1", "Q2", "Q3"]
        q = order[min(3, order.index(q) + 1)]
    return q
