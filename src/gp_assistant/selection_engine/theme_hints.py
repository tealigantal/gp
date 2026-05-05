from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from .chg_normalize import detect_chg_col, normalize_chg_pct
from ..providers.boards import is_mainboard


def _detect_chg_col(cols) -> Optional[str]:
    return detect_chg_col(cols)


def _detect_code_col(df: pd.DataFrame) -> Optional[str]:
    if "代码" in df.columns:
        return "代码"
    if "code" in df.columns:
        return "code"
    return None


def build_mover_hints(snapshot: Optional[pd.DataFrame], topn: int = 3) -> List[Dict[str, Any]]:
    if snapshot is None or (hasattr(snapshot, "empty") and snapshot.empty):
        return []
    df = snapshot.copy()
    code_col = _detect_code_col(df)
    if code_col:
        try:
            df = df[df[code_col].astype(str).map(is_mainboard)]
        except Exception:
            pass
    chg_col = _detect_chg_col(df.columns)
    if not chg_col:
        return []
    df["chg"], ev_scale = normalize_chg_pct(df, chg_col)
    code_col = _detect_code_col(df)
    if not code_col:
        return []
    df2 = df[[code_col, "chg"]].dropna(subset=["chg"]).sort_values("chg", ascending=False).head(max(0, int(topn)))
    out: List[Dict[str, Any]] = []
    for _, row in df2.iterrows():
        try:
            chg_num = float(row.get("chg"))
        except Exception:
            chg_num = float("nan")
        out.append(
            {
                "symbol": row.get(code_col),
                "chg": f"{chg_num:.2f}%" if pd.notna(chg_num) else "",
                "chg_num": chg_num if pd.notna(chg_num) else None,
                "source": "snapshot",
                "evidence": list(ev_scale),
            }
        )
    return out
