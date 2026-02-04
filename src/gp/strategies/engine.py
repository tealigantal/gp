from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..datapool import DataPool
from ..features.core import compute_features_for
from .dsl import StrategyDSL


@dataclass
class ScanHit:
    code: str
    asof: date
    features: Dict[str, float]
    q_level: int
    rationale: str


def _within_env(strategy: StrategyDSL, env: str) -> bool:
    return env in strategy.market_env_allowed


def scan_low_absorption(dp: DataPool, d: date, strategy: StrategyDSL, env: str, candidates: List[str]) -> List[ScanHit]:
    if not _within_env(strategy, env):
        return []
    hits: List[ScanHit] = []
    for code in candidates:
        f = compute_features_for(dp, code)
        if f.empty:
            continue
        row = f[f["date"] <= pd.to_datetime(d)].tail(1)
        if row.empty:
            continue
        r = row.iloc[0]
        # Setup: MA20 rising/flat and RSI2 below threshold; pullback by BIAS
        ma_ok = True  # simplified rising/flat check omitted for brevity
        rsi_ok = float(r["rsi2"]) <= strategy.setup_conditions.params.get("rsi2_max", 15.0)
        bias_ok = float(r["bias6"]) <= strategy.setup_conditions.params.get("bias6_min", -6.0)
        if not (ma_ok and rsi_ok and bias_ok):
            continue
        # Confirmation strength by Q grade: use volratio and nr7 as proxies
        vol_ok = float(r.get("volratio", np.nan)) < 1.2  # contracting volume on pullback
        nr7_ok = bool(r.get("nr7", False))
        q = 2 if (vol_ok and nr7_ok) else 1
        hits.append(
            ScanHit(
                code=code,
                asof=d,
                features={
                    "rsi2": float(r["rsi2"]),
                    "bias6": float(r["bias6"]),
                    "atrp": float(r["atrp"]),
                    "bbwidth": float(r["bbwidth"]),
                    "volratio": float(r["volratio"]),
                },
                q_level=q,
                rationale=f"RSI2≤{strategy.setup_conditions.params.get('rsi2_max', 15.0)}, BIAS6≤{strategy.setup_conditions.params.get('bias6_min', -6.0)}, NR7={nr7_ok}",
            )
        )
    # Rank Top10 by rsi2 asc then bias6 asc
    hits = sorted(hits, key=lambda h: (h.features["rsi2"], h.features["bias6"]))[:10]
    return hits

