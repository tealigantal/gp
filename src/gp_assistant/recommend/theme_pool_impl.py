from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .datahub import MarketDataHub
from .theme_concept import build_concept_themes


def _detect_chg_col(cols) -> Optional[str]:
    names = ["涨跌幅", "涨跌幅(%)", "pct_chg", "涨跌", "changePct"]
    s = set(map(str, cols))
    for n in names:
        if n in s:
            return n
    return None


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
    try:
        df["chg"] = pd.to_numeric(df[chg_col].astype(str).str.rstrip("% ％"), errors="coerce")
    except Exception:
        df["chg"] = pd.to_numeric(df[chg_col], errors="coerce")
    # Heuristic: if values look like decimals (median<1 and max<=1), scale to percent
    scale_note = False
    try:
        med = float(df["chg"].dropna().abs().median()) if len(df) else 0.0
        mx = float(df["chg"].dropna().abs().max()) if len(df) else 0.0
        if (med < 1.0) and (mx <= 1.0) and mx > 0:
            df["chg"] = df["chg"] * 100.0
            scale_note = True
    except Exception:
        pass

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
            if scale_note:
                ev.append("scale:x100")
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
