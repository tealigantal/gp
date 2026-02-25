from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .datahub import MarketDataHub
from .theme_concept import build_concept_themes
from .chg_normalize import detect_chg_col, normalize_chg_pct


def _detect_chg_col(cols) -> Optional[str]:
    # kept for backward import compatibility; delegate to chg_normalize
    return detect_chg_col(cols)


def build_themes_impl(hub: MarketDataHub, snapshot: Optional[pd.DataFrame] = None, topn: int = 2) -> List[Dict[str, Any]]:
    # A) no snapshot
    if snapshot is None or (hasattr(snapshot, "empty") and snapshot.empty):
        return build_concept_themes(topn=topn, reason="no_snapshot") or []

    # B) snapshot present
    snap = snapshot
    chg_col = _detect_chg_col(snap.columns)
    if not chg_col:
        return build_concept_themes(topn=topn, reason="no_chg_col") or []

    df = snap.copy()
    df["chg"], ev_scale = normalize_chg_pct(df, chg_col)

    cols = set(map(str, df.columns))

    # Industry aggregation first
    if "行业" in cols:
        agg = {"chg": ["mean", "count"]}
        has_amt = "成交额" in cols
        if has_amt:
            agg["成交额"] = ["sum"]
        g = df.groupby("行业").agg(agg)
        # flatten columns
        g.columns = ["_".join([c for c in col if c]) for col in g.columns.values]
        # rename
        rename_map = {"chg_mean": "mean_chg", "chg_count": "count"}
        if has_amt:
            rename_map["成交额_sum"] = "sum_amt"
        g = g.rename(columns=rename_map).reset_index()
        g = g.sort_values(["mean_chg"], ascending=False).head(max(0, int(topn)))
        themes: List[Dict[str, Any]] = []
        for _, r in g.iterrows():
            mean_val = r.get("mean_chg")
            try:
                strength = f"{float(mean_val):.2f}%"
            except Exception:
                strength = ""
            ev = [f"样本n={int(r.get('count', 0) or 0)}"]
            ev.extend(ev_scale)
            themes.append({
                "name": str(r.get("行业")),
                "strength": strength,
                "evidence": ev,
                "source": "industry_snapshot",
            })
        return themes

    # No industry column: prefer concept fallback
    t = build_concept_themes(topn=topn, reason="no_industry_col")
    if t:
        return t
    # No industry and no concept: no pseudo themes
    return []
