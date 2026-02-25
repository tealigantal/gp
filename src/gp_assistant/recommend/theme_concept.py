from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import time
import os

# cache and last status for provenance
_CACHE: Dict[str, Any] = {"ts": 0.0, "df": None, "source": None}
_LAST_STATUS: Dict[str, Any] = {"attempted": [], "error": None, "ts": 0.0}


def _ttl() -> int:
    try:
        return int(os.getenv("GP_THEME_CONCEPT_TTL_SEC", "60"))
    except Exception:
        return 60


def last_concept_status() -> Dict[str, Any]:
    return dict(_LAST_STATUS)


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
    now = time.time()
    _LAST_STATUS.update({"attempted": [], "error": None, "ts": now})
    # 0) serve cache if fresh
    try:
        if (_CACHE.get("df") is not None) and (now - float(_CACHE.get("ts", 0.0)) <= _ttl()):
            src = str(_CACHE.get("source") or "concept_board_em")
            return _build_from_df(_CACHE.get("df"), src, topn=topn, reason=reason)
    except Exception:
        pass
    try:
        import akshare as ak  # type: ignore
    except Exception as e:
        _LAST_STATUS.update({"error": f"akshare_import_failed: {e}"})
        return []

    # 1) EM name
    try:
        _LAST_STATUS["attempted"].append("concept_board_em")
        df = ak.stock_board_concept_name_em()  # type: ignore[attr-defined]
        out = _build_from_df(df, "concept_board_em", topn=topn, reason=reason)
        if out:
            _CACHE.update({"ts": now, "df": df, "source": "concept_board_em"})
            return out
    except Exception as e:
        _LAST_STATUS.update({"error": f"concept_board_em_error: {e}"})

    # 2) EM spot (if available) as a secondary path
    try:
        if hasattr(ak, "stock_board_concept_spot_em"):
            _LAST_STATUS["attempted"].append("concept_spot_em")
            df2 = ak.stock_board_concept_spot_em()  # type: ignore[attr-defined]
            out = _build_from_df(df2, "concept_spot_em", topn=topn, reason=reason)
            if out:
                _CACHE.update({"ts": now, "df": df2, "source": "concept_spot_em"})
                return out
    except Exception as e:
        _LAST_STATUS.update({"error": f"concept_spot_em_error: {e}"})

    # 3) THS name fallback
    try:
        _LAST_STATUS["attempted"].append("concept_board_ths")
        df3 = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
        out = _build_from_df(df3, "concept_board_ths", topn=topn, reason=reason)
        if out:
            _CACHE.update({"ts": now, "df": df3, "source": "concept_board_ths"})
            return out
    except Exception as e:
        _LAST_STATUS.update({"error": f"concept_board_ths_error: {e}"})

    return []
