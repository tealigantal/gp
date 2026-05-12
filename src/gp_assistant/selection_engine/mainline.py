from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from .chg_normalize import detect_chg_col, normalize_chg_pct
from ..providers.boards import is_mainboard


def _iso_now() -> str:
    try:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return str(datetime.now())


def _pick_col(df: pd.DataFrame, names: Iterable[str]) -> Optional[str]:
    cols = {str(col): col for col in df.columns}
    for name in names:
        if name in cols:
            return str(cols[name])
    return None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        if pd.isna(parsed):
            return default
        return parsed
    except Exception:
        return default


def _derive_from_candidates(indicator: str, topn: int, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = [item for item in candidates if isinstance(item, dict)]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in rows:
        industry = str(item.get("industry") or "").strip()
        if industry:
            grouped.setdefault(industry, []).append(item)

    sectors: List[Dict[str, Any]] = []
    if grouped:
        max_count = max(1, max(len(items) for items in grouped.values()))
        for name, items in grouped.items():
            avg_candidate = sum(_as_float(item.get("candidate_score")) for item in items) / max(1, len(items))
            avg_strength = sum(_as_float(item.get("industry_strength_score")) for item in items) / max(1, len(items))
            avg_consensus = sum(_as_float(item.get("peer_consensus_score")) for item in items) / max(1, len(items))
            concentration = len(items) / max_count
            score = 0.55 * avg_candidate + 0.20 * avg_strength + 0.15 * avg_consensus + 0.10 * concentration
            leader = max(items, key=lambda item: _as_float(item.get("candidate_score")))
            sectors.append(
                {
                    "sector_type": "derived_industry",
                    "name": name,
                    "score": round(float(score), 6),
                    "sample_count": len(items),
                    "leader_stock": str(leader.get("symbol") or ""),
                    "leader_name": leader.get("name"),
                    "source": "derived:daily_universe",
                    "indicator": indicator,
                }
            )
        sectors.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    else:
        ranked = sorted(rows, key=lambda item: _as_float(item.get("candidate_score")), reverse=True)
        for item in ranked[: max(0, int(topn))]:
            symbol = str(item.get("symbol") or item.get("code") or "").strip()
            if not symbol:
                continue
            sectors.append(
                {
                    "sector_type": "derived_leader",
                    "name": f"强势线索-{symbol}",
                    "score": round(_as_float(item.get("candidate_score")), 6),
                    "sample_count": 1,
                    "leader_stock": symbol,
                    "leader_name": item.get("name"),
                    "source": "derived:daily_universe",
                    "indicator": indicator,
                }
            )

    return {
        "indicator": indicator,
        "sectors": sectors[: max(0, int(topn))],
        "as_of_ts": _iso_now(),
        "errors": [],
        "source": "derived:daily_universe",
    }


def _derive_from_snapshot(indicator: str, topn: int, snapshot: pd.DataFrame) -> Dict[str, Any]:
    df = snapshot.copy()
    code_col = _pick_col(df, ["code", "代码", "ts_code"])
    name_col = _pick_col(df, ["name", "名称", "symbol"])
    amount_col = _pick_col(df, ["amount", "成交额"])
    if code_col:
        try:
            df = df[df[code_col].astype(str).map(is_mainboard)]
        except Exception:
            pass
    chg_col = detect_chg_col(df.columns)
    errors: List[str] = []
    if not chg_col:
        return {
            "indicator": indicator,
            "sectors": [],
            "as_of_ts": _iso_now(),
            "errors": ["snapshot_chg_col_missing"],
            "source": "derived:market_snapshot",
        }

    df["_mainline_pct"], scale_notes = normalize_chg_pct(df, chg_col)
    df["_mainline_amount"] = pd.to_numeric(df.get(amount_col), errors="coerce") if amount_col else 0.0
    df = df.dropna(subset=["_mainline_pct"]).copy()
    if df.empty:
        errors.append("snapshot_pct_empty")

    sectors: List[Dict[str, Any]] = []
    ranked = df.sort_values(["_mainline_pct", "_mainline_amount"], ascending=[False, False]).head(max(0, int(topn)))
    for _, row in ranked.iterrows():
        symbol = str(row.get(code_col) or "").strip() if code_col else ""
        name = str(row.get(name_col) or symbol).strip() if name_col else symbol
        pct = _as_float(row.get("_mainline_pct"))
        amount = _as_float(row.get("_mainline_amount"))
        sectors.append(
            {
                "sector_type": "derived_leader",
                "name": f"强势线索-{symbol or name}",
                "pct_chg": round(pct, 4),
                "amount": amount,
                "score": round(pct + min(amount / 1_000_000_000.0, 5.0) * 0.05, 6),
                "sample_count": 1,
                "leader_stock": symbol or None,
                "leader_name": name or None,
                "source": "derived:market_snapshot",
                "indicator": indicator,
                "evidence": list(scale_notes),
            }
        )

    return {
        "indicator": indicator,
        "sectors": sectors,
        "as_of_ts": _iso_now(),
        "errors": errors,
        "source": "derived:market_snapshot",
    }


def build_mainline(
    indicator: str = "今日",
    topn: int = 3,
    snapshot: Optional[pd.DataFrame] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the market mainline from local full-market and daily-universe data only."""

    if candidates:
        derived = _derive_from_candidates(indicator, topn, candidates)
        if derived.get("sectors"):
            return derived

    if snapshot is not None and isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
        return _derive_from_snapshot(indicator, topn, snapshot)

    return {
        "indicator": indicator,
        "sectors": [],
        "as_of_ts": _iso_now(),
        "errors": ["market_data_missing"],
        "source": "derived:unavailable",
    }
