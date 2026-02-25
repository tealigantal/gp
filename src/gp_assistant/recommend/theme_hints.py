from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def _detect_chg_col(cols) -> Optional[str]:
    names = ["涨跌幅", "涨跌幅(%)", "pct_chg", "涨跌", "changePct"]
    s = set(map(str, cols))
    for n in names:
        if n in s:
            return n
    return None


def build_mover_hints(snapshot: Optional[pd.DataFrame], topn: int = 3) -> List[Dict[str, Any]]:
    if snapshot is None or (hasattr(snapshot, "empty") and snapshot.empty):
        return []
    df = snapshot.copy()
    chg_col = _detect_chg_col(df.columns)
    if not chg_col:
        return []
    try:
        df["chg"] = pd.to_numeric(df[chg_col].astype(str).str.rstrip("% ％"), errors="coerce")
    except Exception:
        df["chg"] = pd.to_numeric(df[chg_col], errors="coerce")
    code_col = "代码" if "代码" in df.columns else ("code" if "code" in df.columns else None)
    if not code_col:
        return []
    df2 = df[[code_col, "chg"]].dropna(subset=["chg"]).sort_values("chg", ascending=False).head(max(0, int(topn)))
    out: List[Dict[str, Any]] = []
    for _, r in df2.iterrows():
        try:
            strength = f"{float(r.get('chg')):.2f}%"
        except Exception:
            strength = ""
        out.append({"symbol": r.get(code_col), "chg": strength, "source": "snapshot"})
    return out

