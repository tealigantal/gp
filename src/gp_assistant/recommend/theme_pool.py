# 简介：主题池构建（严格模式）。基于全市场快照的短期相对强度给出主线线索。
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from .datahub import MarketDataHub
from ..providers.factory import get_provider


def build_themes(hub: MarketDataHub) -> List[Dict[str, Any]]:
    # 优先使用快照中的行业列，按行业聚合给出主线；缺列则退为个股强势线索（仍来自真实快照）
    p = get_provider()
    snap = p.get_spot_snapshot()
    cols = set(snap.columns)
    chg_col = None
    for c in ("涨跌幅", "涨跌幅(%)", "pct_chg", "涨跌", "changePct"):
        if c in cols:
            chg_col = c
            break
    if not chg_col:
        return []
    # normalize change
    import pandas as pd
    df = snap.copy()
    df["chg"] = pd.to_numeric(df[chg_col].astype(str).str.rstrip("% "), errors="coerce")
    # Industry-aggregated themes
    if "行业" in cols:
        # Aggregate by industry: mean change and sum of amount when available
        if "成交额" in cols:
            g = df.groupby("行业").agg(mean_chg=("chg", "mean"), sum_amt=("成交额", "sum"), count=("chg", "count")).reset_index()
        else:
            g = df.groupby("行业").agg(mean_chg=("chg", "mean"), count=("chg", "count")).reset_index()
        g = g.sort_values(["mean_chg"], ascending=False).head(2)
        themes: List[Dict[str, Any]] = []
        for _, r in g.iterrows():
            themes.append({
                "name": str(r["行业"]),
                "strength": f"{float(r['mean_chg']):.2f}%",
                "evidence": [f"行业均值涨跌幅 {float(r['mean_chg']):.2f}%", f"样本数 {int(r['count'])}"],
            })
        return themes
    # 尝试概念板块强度（akshare）
    try:
        import akshare as ak  # type: ignore
        cons_name = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
        if cons_name is not None and len(cons_name) > 0:
            rank_col = None
            for c in ("涨跌幅", "涨跌幅(%)", "涨跌", "changePct"):
                if c in cons_name.columns:
                    rank_col = c
                    break
            import pandas as pd
            cn = cons_name.copy()
            if rank_col:
                try:
                    cn["_r"] = pd.to_numeric(cn[rank_col].astype(str).str.rstrip("% "), errors="coerce")
                except Exception:
                    cn["_r"] = pd.to_numeric(cn[rank_col], errors="coerce")
                cn = cn.sort_values("_r", ascending=False).head(2)
            else:
                cn = cn.head(2)
            name_col = "板块名称" if "板块名称" in cn.columns else cn.columns[0]
            out: List[Dict[str, Any]] = []
            for _, r in cn.iterrows():
                out.append({
                    "name": f"概念-{str(r[name_col])}",
                    "strength": str(float(r.get("_r", 0.0))) if "_r" in r else "",
                    "evidence": ["来源：概念板块排行"],
                })
            return out
    except Exception:
        pass
    # fallback: top movers by code (仍是快照真实数据)
    code_col = "代码" if "代码" in cols else ("code" if "code" in cols else None)
    if not code_col:
        return []
    df2 = df[[code_col, "chg"]].rename(columns={code_col: "code"}).sort_values("chg", ascending=False).head(2)
    themes: List[Dict[str, Any]] = []
    for _, r in df2.iterrows():
        themes.append({
            "name": f"强势线索-{r['code']}",
            "strength": f"{float(r['chg']):.2f}%",
            "evidence": [f"当日领涨：{float(r['chg']):.2f}%"],
        })
    return themes
