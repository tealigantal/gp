from __future__ import annotations

"""
Utilities to detect, parse and normalize change percentage columns without guessing units.

Principles:
- Do not guess scale. Only infer when there is verifiable evidence.
- When evidence is missing, treat raw numbers as percentages (no scaling) but record evidence
  to make this assumption visible to the user interface.
"""

from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd


_CANDIDATE_CHG_COLS: Tuple[str, ...] = (
    "涨跌幅",
    "涨跌幅(%)",
    "pct_chg",
    "涨跌",
    "changePct",
)

_PRICE_COLS: Tuple[str, ...] = (
    "最新价",
    "收盘",
    "close",
    "price",
    "last",
)

_CHG_AMOUNT_COLS: Tuple[str, ...] = (
    "涨跌额",
    "change",
    "chg_amt",
)


def detect_chg_col(cols: Iterable[str]) -> Optional[str]:
    s = set(map(str, cols))
    for n in _CANDIDATE_CHG_COLS:
        if n in s:
            return n
    return None


def parse_chg_raw(df: pd.DataFrame, chg_col: str) -> pd.Series:
    """Parse change column into numeric float series without scaling.

    - Strips trailing percent symbols when present.
    - Returns numeric series; non-parsable values become NaN.
    - Does NOT multiply by 100; scaling is handled separately.
    """
    try:
        ser = pd.to_numeric(df[chg_col].astype(str).str.rstrip("% ％"), errors="coerce")
    except Exception:
        ser = pd.to_numeric(df[chg_col], errors="coerce")
    return ser


def _first_present(df: pd.DataFrame, names: Sequence[str]) -> Optional[str]:
    s = set(map(str, df.columns))
    for n in names:
        if n in s:
            return n
    return None


def infer_scale_by_implied_pct(df: pd.DataFrame) -> Optional[float]:
    """Infer scaling factor for change numbers using implied percent evidence.

    If both price (latest) and change amount columns exist, compute implied_pct = chg_amt / price * 100.
    Compare typical magnitudes against the raw change column:
      - ratio in [80, 120] => raw is decimal (0.01 ~ 1%), scale=100
      - ratio in [0.8, 1.25] => raw already %, scale=1
      - otherwise => None (do not infer)
    When columns are missing, return None.
    """
    chg_col = detect_chg_col(df.columns)
    if not chg_col:
        return None
    price_col = _first_present(df, _PRICE_COLS)
    amt_col = _first_present(df, _CHG_AMOUNT_COLS)
    if not price_col or not amt_col:
        return None
    try:
        raw = parse_chg_raw(df, chg_col)
        price = pd.to_numeric(df[price_col], errors="coerce")
        amt = pd.to_numeric(df[amt_col], errors="coerce")
        implied_pct = (amt / price) * 100.0
        # robust medians on absolute values
        med_imp = float(implied_pct.abs().median()) if len(df) else float("nan")
        med_raw = float(raw.abs().median()) if len(df) else float("nan")
        if not pd.isna(med_imp) and not pd.isna(med_raw) and med_imp > 0 and med_raw > 0:
            ratio = med_imp / med_raw
            if 80.0 <= ratio <= 120.0:
                return 100.0
            if 0.8 <= ratio <= 1.25:
                return 1.0
    except Exception:
        return None
    return None


def normalize_chg_pct(df: pd.DataFrame, chg_col: str) -> Tuple[pd.Series, List[str]]:
    """Return percentage series and evidence list.

    Behavior:
    - Always parse raw numbers via parse_chg_raw (strip % but no scaling).
    - If infer_scale_by_implied_pct returns 100, multiply by 100 and record evidence.
    - If it returns 1, keep as-is and record evidence.
    - If None, keep as-is and add evidence "scale:assume_pct_no_evidence" to make the assumption visible.
    """
    raw = parse_chg_raw(df, chg_col)
    scale = infer_scale_by_implied_pct(df)
    evid: List[str] = []
    if scale == 100.0:
        out = raw * 100.0
        evid.append("scale:implied_pct_ratio~100")
        return out, evid
    if scale == 1.0:
        out = raw
        evid.append("scale:implied_pct_ratio~1")
        return out, evid
    evid.append("scale:assume_pct_no_evidence")
    return raw, evid

