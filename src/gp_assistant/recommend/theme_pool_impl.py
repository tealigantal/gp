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
            themes.append({
                "name": str(r.get("行业")),
                "strength": strength,
                "evidence": [f"样本n={int(r.get('count', 0) or 0)}"],
                "source": "industry_snapshot",
            })
        return themes

    # No industry column: prefer concept fallback
    t = build_concept_themes(topn=topn, reason="no_industry_col")
    if t:
        return t

    # Fallback: top movers by code from snapshot
    code_col = "代码" if "代码" in cols else ("code" if "code" in cols else None)
    if not code_col:
        return []
    df2 = df[[code_col, "chg"]].dropna(subset=["chg"]).sort_values("chg", ascending=False).head(max(0, int(topn)))
    themes: List[Dict[str, Any]] = []
    for _, r in df2.iterrows():
        val = r.get("chg")
        try:
            strength = f"{float(val):.2f}%"
        except Exception:
            strength = ""
        themes.append({
            "name": f"强势线索-{r.get(code_col)}",
            "strength": strength,
            "evidence": [f"当日领涨：{strength}" if strength else "当日领涨"],
            "source": "top_movers",
        })
    return themes

