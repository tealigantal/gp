# 简介：候选生成器。基于基础池与市场环境生成候选标的集合，
# 同时返回被否决/过滤的原因以便调试与解释。
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from .datahub import MarketDataHub
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip
from ..risk.noise_q import grade_noise


def _liquidity_grade(avg5_amount: float) -> str:
    if avg5_amount >= 2e9:
        return "A"
    if avg5_amount >= 1e9:
        return "B"
    return "C"


def generate_candidates(symbols: List[str], env_grade: str, topk: int = 3) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    hub = MarketDataHub()
    pool: List[Dict[str, Any]] = []
    veto_reasons = []
    for sym in symbols:
        df, _ = hub.daily_ohlcv(sym, None, min_len=250)
        feat = compute_indicators(df)
        # facts
        last = feat.iloc[-1]
        avg5_amount = float(feat["amount_5d_avg"].iloc[-1]) if not pd.isna(feat["amount_5d_avg"].iloc[-1]) else 0.0
        atrp = float(last["atr_pct"]) if not pd.isna(last["atr_pct"]) else 0.0
        gap = float(last["gap_pct"]) if not pd.isna(last["gap_pct"]) else 0.0
        close = float(last["close"]) if not pd.isna(last["close"]) else 0.0
        ma20 = float(last["ma20"]) if not pd.isna(last["ma20"]) else 0.0
        # pressure flags
        pressure = {"near_ma20": bool(ma20 and abs((close - ma20) / ma20) <= 0.005)}
        # chip
        chip, chip_meta = compute_chip(feat)
        q_grade = grade_noise(feat, env_grade)

        cand = {
            "symbol": sym,
            "name": None,
            "source_reason": "默认候选池",
            "liquidity": {"avg5_amount": avg5_amount, "grade": _liquidity_grade(avg5_amount)},
            "atr_pct": atrp,
            "gap_pct": gap,
            "pressure_flags": pressure,
            "q_grade": q_grade,
            "chip": chip.__dict__,
            "indicators": {
                "ma20": ma20,
                "slope20": float(feat["slope20"].iloc[-1]) if "slope20" in feat.columns else 0.0,
                "atr_pct": atrp,
                "gap_pct": gap,
            },
            "close": close,
        }
        # One-vote veto and observe flags
        observe_only = False
        reasons: List[str] = []
        if cand["liquidity"]["grade"] == "C":
            observe_only = True
            reasons.append("流动性C：仅观察仓")
        if atrp > 0.08:
            observe_only = True
            reasons.append("ATR%>8%：仅观察/降仓")
        if gap > 0.02:
            observe_only = True
            reasons.append("Gap>+2%：当日禁买")
        if chip.dist_to_90_high_pct <= 0.02:
            observe_only = True
            reasons.append("贴近筹码90%上限：当日禁买")
        cand["flags"] = {"must_observe_only": bool(observe_only), "reasons": reasons}
        pool.append(cand)
    # rank by simple slope20 then by lower ATR and liquidity grade
    pool.sort(key=lambda x: (-(x["indicators"]["slope20"] or 0.0), x["atr_pct"], x["liquidity"]["grade"]))
    return pool, veto_reasons
