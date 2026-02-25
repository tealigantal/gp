from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def _detect_rank_col(df: pd.DataFrame) -> Optional[str]:
    candidates = ["涨跌幅", "涨跌幅(%)", "涨跌", "changePct", "pct_chg"]
    cols = set(map(str, df.columns))
    for c in candidates:
        if c in cols:
            return c
    return None


def _normalize_strength(v: Any) -> str:
    try:
        s = pd.to_numeric(str(v).strip().rstrip("%％").replace(",", ""), errors="coerce")
        if pd.isna(s):
            return ""
        return f"{float(s):.2f}%"
    except Exception:
        return ""


def _build_from_df(df: pd.DataFrame, source: str, *, topn: int, reason: Optional[str]) -> List[Dict[str, Any]]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    rank_col = _detect_rank_col(df)
    if not rank_col:
        return []
    x = df.copy()
    try:
        x["_r"] = pd.to_numeric(x[rank_col].astype(str).str.rstrip("% ％"), errors="coerce")
    except Exception:
        x["_r"] = pd.to_numeric(x[rank_col], errors="coerce")
    # If all ranks are NaN, do not fabricate themes
    x_valid = x.dropna(subset=["_r"]).copy()
    if x_valid.empty:
        return []
    x = x_valid.sort_values("_r", ascending=False)
    name_col = "板块名称" if "板块名称" in x.columns else str(list(x.columns)[0])
    out: List[Dict[str, Any]] = []
    for _, r in x.head(max(0, int(topn))).iterrows():
        strength = _normalize_strength(r.get("_r", None))
        ev = ["来源：概念板块排行"]
        if reason:
            ev.append(f"触发：{reason}")
        out.append({
            "name": f"概念-{str(r.get(name_col))}",
            "strength": strength,
            "evidence": ev,
            "source": source,
        })
    return out


def build_concept_themes(topn: int = 2, reason: Optional[str] = None) -> List[Dict[str, Any]]:
    """Build weak mainline themes from AkShare concept boards.

    Order:
    - stock_board_concept_name_em -> concept_board_em
    - if no usable rank column: stock_board_concept_spot_em -> concept_spot_em
    - fallback: stock_board_concept_name_ths -> concept_board_ths
    Returns [] when no change/rank column available (no pseudo themes).
    """
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return []

    # 1) EM name
    try:
        df = ak.stock_board_concept_name_em()  # type: ignore[attr-defined]
        out = _build_from_df(df, "concept_board_em", topn=topn, reason=reason)
        if out:
            return out
    except Exception:
        pass

    # 2) EM spot (if available) as a secondary path
    try:
        if hasattr(ak, "stock_board_concept_spot_em"):
            df2 = ak.stock_board_concept_spot_em()  # type: ignore[attr-defined]
            out = _build_from_df(df2, "concept_spot_em", topn=topn, reason=reason)
            if out:
                return out
    except Exception:
        pass

    # 3) THS name fallback
    try:
        df3 = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
        out = _build_from_df(df3, "concept_board_ths", topn=topn, reason=reason)
        if out:
            return out
    except Exception:
        pass

    return []
