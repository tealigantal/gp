# 简介：市场环境打分。汇总大盘与成交额等简要特征，给出分层等级与恢复条件。
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from .datahub import MarketDataHub


def score_regime(hub: MarketDataHub, snapshot: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """基于全市场快照的环境分层（严格模式，无指数合成降级）。
    逻辑：使用全市场涨跌幅分布与涨跌家数评估环境。
    """
    if snapshot is None:
        return {
            "grade": "C",
            "reasons": ["no_snapshot_universe_mode"],
            "recovery_conditions": ["提供实时快照后可细化环境分层"],
            "raw": {"breadth": {"mean_chg": None, "up_ratio": None}},
        }
    snap = snapshot
    # 统一 pct_chg 列（中英/括号/% 兼容）
    def _norm(s: str) -> str:
        x = (s or "").strip().lower()
        x = x.replace("（", "(").replace("）", ")").replace("％", "%").replace("%", "")
        x = "".join(x.split())
        return x
    cands = ["涨跌幅", "涨跌幅(%)", "涨跌", "pct_chg", "changepct", "change_pct", "pct_change"]
    cmap = { _norm(c): c for c in snap.columns }
    src = None
    for k in cands:
        nk = _norm(k)
        if nk in cmap:
            src = cmap[nk]
            break
    if src and "pct_chg" not in snap.columns:
        snap = snap.copy()
        snap["pct_chg"] = snap[src]
    if "pct_chg" not in snap.columns:
        raise RuntimeError("快照缺少涨跌幅列，无法评估环境")
    # 量纲修正：小数 -> 百分比
    s = pd.to_numeric(snap["pct_chg"], errors="coerce")
    try:
        median_abs = float(s.abs().median()) if not s.abs().isna().all() else None
        max_abs = float(s.abs().max()) if not s.abs().isna().all() else None
        if median_abs is not None and max_abs is not None and median_abs < 1 and max_abs <= 1.0:
            s = s * 100.0
    except Exception:
        pass
    snap = snap.copy()
    snap["pct_chg"] = s
    df = snap[["pct_chg"]].rename(columns={"pct_chg": "chg"}).copy()
    df = df.dropna()
    mean_chg = float(df["chg"].mean())
    up_ratio = float((df["chg"] > 0).mean())
    reasons = [f"全市场均值涨跌幅={mean_chg:.2f}%", f"上涨占比={up_ratio:.2%}"]
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

