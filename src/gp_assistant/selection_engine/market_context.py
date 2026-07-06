from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from ..runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    compute_market_state,
)
from .tail_risk import safe_float


TAIL_CONTEXT_PHASES = {
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_CLOSING_AUCTION,
}


def _normalize_code(value: Any) -> str:
    s = str(value or "").strip().lower()
    if "." in s:
        s = s.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _pick_col(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    cols = {str(col).strip().lower(): col for col in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower()
        if key in cols:
            return str(cols[key])
    return None


def _numeric_series(df: pd.DataFrame, col: str | None) -> pd.Series:
    if not col or col not in df.columns:
        return pd.Series(dtype="float64")
    series = df[col]
    try:
        if series.dtype == object:
            series = series.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
        return pd.to_numeric(series, errors="coerce")
    except Exception:
        return pd.to_numeric(df[col], errors="coerce")


def build_market_context(
    snapshot: pd.DataFrame | None,
    snapshot_meta: Mapping[str, Any] | None = None,
    *,
    market_state: Any = None,
) -> Dict[str, Any]:
    state = market_state or compute_market_state()
    phase = str(getattr(state, "market_phase", "") or "")
    active = phase in TAIL_CONTEXT_PHASES
    meta = dict(snapshot_meta or {})
    base: Dict[str, Any] = {
        "status": "unavailable",
        "phase": phase,
        "used_for_tail_confirmation": False,
        "source": meta.get("source") or meta.get("cache_of"),
        "as_of_ts": meta.get("as_of_ts"),
        "rows": 0,
        "reason": None,
        "breadth": {},
        "symbols": {},
    }

    if snapshot is None or not isinstance(snapshot, pd.DataFrame) or snapshot.empty:
        base["reason"] = "snapshot_unavailable"
        return base

    if not active:
        base["status"] = "inactive_phase"
        base["reason"] = "not_intraday_tail_phase"
    else:
        base["status"] = "available"
        base["used_for_tail_confirmation"] = True

    df = snapshot.copy()
    code_col = _pick_col(df, ["code", "代码", "symbol", "ts_code"])
    price_col = _pick_col(df, ["price", "最新价", "现价", "close", "最新"])
    pct_col = _pick_col(df, ["pct_chg", "涨跌幅", "涨跌幅(%)", "涨幅", "changePct"])
    amount_col = _pick_col(df, ["amount", "成交额", "成交额(元)", "turnover"])
    high_col = _pick_col(df, ["high", "最高", "最高价", "day_high"])
    low_col = _pick_col(df, ["low", "最低", "最低价", "day_low"])
    open_col = _pick_col(df, ["open", "今开", "开盘", "day_open"])
    prev_close_col = _pick_col(df, ["prev_close", "昨收", "previous_close"])

    if code_col is None or price_col is None:
        base["status"] = "unavailable"
        base["used_for_tail_confirmation"] = False
        base["reason"] = "snapshot_schema_missing"
        base["rows"] = int(len(df))
        return base

    prices = _numeric_series(df, price_col)
    pct = _numeric_series(df, pct_col)
    amount = _numeric_series(df, amount_col)
    high = _numeric_series(df, high_col)
    low = _numeric_series(df, low_col)
    open_ = _numeric_series(df, open_col)
    prev_close = _numeric_series(df, prev_close_col)
    symbols: Dict[str, Any] = {}
    for idx, row in df.iterrows():
        code = _normalize_code(row.get(code_col))
        if not code:
            continue
        price = safe_float(prices.get(idx))
        if price is None:
            continue
        day_high = safe_float(high.get(idx))
        day_low = safe_float(low.get(idx))
        day_open = safe_float(open_.get(idx))
        prev = safe_float(prev_close.get(idx))
        pct_chg = safe_float(pct.get(idx))
        amt = safe_float(amount.get(idx))
        symbols[code] = {
            "current_price": price,
            "pct_chg": pct_chg,
            "day_high": day_high,
            "day_low": day_low,
            "day_open": day_open,
            "prev_close": prev,
            "amount": amt,
        }

    pct_clean = pct.dropna()
    base["rows"] = int(len(df))
    base["symbols"] = symbols
    if not pct_clean.empty:
        base["breadth"] = {
            "mean_pct_chg": float(pct_clean.mean()),
            "median_pct_chg": float(pct_clean.median()),
            "up_ratio": float((pct_clean > 0).mean()),
        }
    if not amount.empty:
        base.setdefault("breadth", {})["total_amount"] = float(amount.fillna(0).sum())
    return base


def _item_support(item: Mapping[str, Any]) -> float | None:
    tp = item.get("trade_plan") if isinstance(item, Mapping) else {}
    if not isinstance(tp, Mapping):
        return None
    candidates: List[Any] = []
    stop_obj = tp.get("stop")
    if isinstance(stop_obj, Mapping):
        candidates.append(stop_obj.get("price"))
    for band_key in ("bands", "execution_bands", "structural_bands"):
        bands = tp.get(band_key)
        if isinstance(bands, Mapping):
            candidates.append(bands.get("S1"))
    numeric = [safe_float(v) for v in candidates]
    numeric = [v for v in numeric if v is not None and v > 0]
    return max(numeric) if numeric else None


def annotate_tail_confirmation(
    items: List[Dict[str, Any]],
    market_context: Mapping[str, Any],
    *,
    env: Mapping[str, Any] | None = None,
) -> None:
    symbols = market_context.get("symbols") if isinstance(market_context, Mapping) else {}
    symbol_map = symbols if isinstance(symbols, Mapping) else {}
    active = bool(market_context.get("used_for_tail_confirmation") is True)
    env_grade = str((env or {}).get("grade") or "").upper()
    env_adj = {"A": 0.10, "B": -0.20, "C": 0.0, "D": -0.35}.get(env_grade, 0.0)

    for item in items:
        code = _normalize_code(item.get("symbol"))
        snap = symbol_map.get(code) if code else None
        support = _item_support(item)
        reasons: List[str] = []
        score = 0.50 + env_adj
        penalty = 0.0
        blocked = False
        if env_grade in {"B", "D"}:
            reasons.append(f"market_env_{env_grade}_position_reduced")
        if not active:
            reasons.append("market_context_inactive")
        elif not isinstance(snap, Mapping):
            reasons.append("symbol_spot_missing")
        else:
            price = safe_float(snap.get("current_price"))
            day_high = safe_float(snap.get("day_high"))
            day_low = safe_float(snap.get("day_low"))
            pct_chg = safe_float(snap.get("pct_chg"))
            if price is not None and support is not None:
                if price < support:
                    blocked = True
                    penalty -= 2.0
                    score -= 0.45
                    reasons.append("tail_below_stop_or_support")
                else:
                    score += 0.18
                    reasons.append("tail_above_stop_or_support")
                    if day_low is not None and day_low < support:
                        penalty -= 0.20
                        reasons.append("intraday_recovered_support")
            if price is not None and day_high is not None and day_low is not None and day_low > 0:
                if day_high / day_low - 1.0 >= 0.08 and price < day_high * 0.985:
                    penalty -= 0.18
                    score -= 0.15
                    reasons.append("intraday_spike_faded")
            if pct_chg is not None and pct_chg >= 7.0:
                penalty -= 0.12
                score -= 0.10
                reasons.append("intraday_overextended")
            item["market_context_snapshot"] = {
                "current_price": snap.get("current_price"),
                "pct_chg": snap.get("pct_chg"),
                "day_high": snap.get("day_high"),
                "day_low": snap.get("day_low"),
                "day_open": snap.get("day_open"),
                "prev_close": snap.get("prev_close"),
                "amount": snap.get("amount"),
            }

        score = max(0.0, min(1.0, score))
        item["tail_confirmation_score"] = float(score)
        item["breakdown_penalty"] = float(penalty)
        item["tail_entry_blocked"] = bool(blocked)
        item["midday_adjustment_reason_codes"] = reasons
