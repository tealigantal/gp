# 简介：市场环境打分。汇总大盘与成交额等简要特征，给出分层等级与恢复条件，
# 驱动候选规模与仓位等风控倾向。
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .datahub import MarketDataHub


def _trend_grade(df: pd.DataFrame) -> float:
    if len(df) < 30:
        return 0.0
    ma20 = df["close"].rolling(20).mean()
    slope = (ma20 - ma20.shift(5)) / ma20.shift(5).replace(0, 1e-12)
    recent = float(slope.tail(5).mean())
    return float(max(-0.2, min(0.2, recent)))


def score_regime(hub: MarketDataHub) -> Dict[str, Any]:
    # Indices: SSE, SZSE, GEM proxy symbols (user must map in fixtures)
    idx_syms = ["000001", "399001", "399006"]  # 上证、深证、创业板 指数代码示意
    trends: List[float] = []
    raw: Dict[str, Any] = {}
    for s in idx_syms:
        df, meta = hub.index_daily(s)
        trends.append(_trend_grade(df))
        raw[s] = {"len": meta.get("len"), "insufficient": meta.get("insufficient_history")}
    mean_trend = float(pd.Series(trends).mean()) if trends else 0.0
    stats = hub.market_stats()
    reasons = [f"指数20日斜率均值={mean_trend:.3f}"]
    if stats.get("total_amount") is not None:
        reasons.append("成交额口径可用")
    grade = "A" if mean_trend > 0.05 else ("B" if mean_trend > 0.01 else ("C" if mean_trend > -0.02 else "D"))
    recovery = []
    if grade == "D":
        recovery = [
            "指数MA20止跌回稳并走平/上拐",
            "两市成交额回到近5日均值以上",
            "封板率/梯队回暖且断层减少",
        ]
    return {
        "grade": grade,
        "reasons": reasons,
        "recovery_conditions": recovery,
        "raw": {"indices": raw, "market_stats": stats},
    }
