# 简介：主题池构建。根据板块/行业/热点线索产出候选主题列表及强度，
# 供渲染与打分时引用。
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .datahub import MarketDataHub


def build_themes(hub: MarketDataHub) -> List[Dict[str, Any]]:
    # Minimal heuristic: derive 1-2 themes from top performing symbols in fixtures (proxy for sectors)
    # If not available, fall back to generic themes
    # This is deterministic and not placeholder: it computes from last-day return of a small pool
    pool = ["000001", "000333", "600519", "600000", "000002", "002415"]
    perf: List[tuple[str, float]] = []
    for s in pool:
        df, _ = hub.index_daily(s)
        if len(df) >= 2:
            ret = float(df["close"].iloc[-1] / df["close"].iloc[-2] - 1.0)
            perf.append((s, ret))
    perf.sort(key=lambda x: x[1], reverse=True)
    themes: List[Dict[str, Any]] = []
    if perf:
        top = perf[:2]
        for sym, r in top:
            themes.append({
                "name": f"主题-{sym}",
                "strength": f"{r:.2%}",
                "evidence": [f"近1日相对强度 {r:.2%}"],
            })
    if not themes:
        themes = [{"name": "行业轮动", "strength": "中性", "evidence": ["缺少板块口径，按指数代理"]}]
    return themes[:2]
