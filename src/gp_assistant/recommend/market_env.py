# 简介：市场环境打分。汇总大盘与成交额等简要特征，给出分层等级与恢复条件，
# 驱动候选规模与仓位等风控倾向。
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from .datahub import MarketDataHub
from ..providers.factory import get_provider


def score_regime(hub: MarketDataHub) -> Dict[str, Any]:
    """基于全市场快照的环境分层（严格模式，无指数合成/降级）。

    逻辑：使用全市场涨跌幅分布与涨跌家数评估环境。
    """
    p = get_provider()
    snap = p.get_spot_snapshot()
    # 识别涨跌幅列
    chg_col = None
    for c in ("涨跌幅", "涨跌幅(%)", "pct_chg", "涨跌", "changePct"):
        if c in snap.columns:
            chg_col = c
            break
    if not chg_col:
        raise RuntimeError("快照缺少涨跌幅列，无法评估环境")
    df = snap[[chg_col]].rename(columns={chg_col: "chg"}).copy()
    try:
        df["chg"] = df["chg"].astype(str).str.rstrip("% ").astype(float)
    except Exception:
        df["chg"] = pd.to_numeric(df["chg"], errors="coerce")
    df = df.dropna()
    mean_chg = float(df["chg"].mean())
    up_ratio = float((df["chg"] > 0).mean())
    reasons = [f"全市场均值涨跌幅={mean_chg:.2f}%", f"上涨占比={up_ratio:.2%}"]
    # 简化分层规则（可配置）：
    grade = "A" if mean_chg > 1.0 and up_ratio > 0.6 else (
        "B" if mean_chg > 0.3 and up_ratio > 0.55 else (
            "C" if mean_chg > -0.3 and up_ratio > 0.45 else "D"
        )
    )
    recovery = []
    if grade == "D":
        recovery = [
            "上涨家数占比>55%",
            "全市场均值涨跌幅>+0.3%",
        ]
    return {
        "grade": grade,
        "reasons": reasons,
        "recovery_conditions": recovery,
        "raw": {"breadth": {"mean_chg": mean_chg, "up_ratio": up_ratio}},
    }
