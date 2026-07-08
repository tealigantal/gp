from __future__ import annotations

from typing import Any, Dict, Iterable, List

import pandas as pd

from ..market_memory.store import load_decision_snapshot, save_prediction_outcome
from ..selection_engine.datahub import MarketDataHub
from .counterfactual import analyze_regret, classify_prediction_error


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _future_outcome(symbol: str, *, as_of: str, horizon: int = 5) -> Dict[str, Any]:
    hub = MarketDataHub()
    df, meta = hub.daily_ohlcv(symbol, as_of=None, min_len=80, prefer_cache_only=True)
    if df is None or df.empty or "date" not in df.columns:
        return {"complete": False, "reason": "daily_data_missing", "data_meta": meta}
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    target = pd.to_datetime(as_of).normalize()
    matches = work.index[work["date"].dt.normalize() == target]
    if len(matches) == 0:
        return {"complete": False, "reason": "as_of_not_found", "data_meta": meta}
    idx = int(matches[0])
    if idx + horizon >= len(work):
        return {"complete": False, "reason": "future_window_not_available", "data_meta": meta}
    entry = _safe_float(work["close"].iloc[idx])
    if entry <= 0:
        return {"complete": False, "reason": "entry_price_invalid", "data_meta": meta}
    fwd = work.iloc[idx + 1 : idx + horizon + 1]
    closes = pd.to_numeric(fwd["close"], errors="coerce")
    highs = pd.to_numeric(fwd["high"], errors="coerce") if "high" in fwd.columns else closes
    lows = pd.to_numeric(fwd["low"], errors="coerce") if "low" in fwd.columns else closes
    return {
        "complete": True,
        "return_1d": _safe_float(closes.iloc[0] / entry - 1.0),
        "return_3d": _safe_float(closes.iloc[min(2, len(closes) - 1)] / entry - 1.0),
        "return_5d": _safe_float(closes.iloc[min(4, len(closes) - 1)] / entry - 1.0),
        "max_profit": _safe_float(highs.max() / entry - 1.0),
        "max_drawdown": _safe_float(lows.min() / entry - 1.0),
        "success": bool(_safe_float(closes.iloc[min(2, len(closes) - 1)] / entry - 1.0) > 0.0),
        "data_meta": meta,
    }


def _candidate_map(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(row.get("symbol")): dict(row) for row in rows if row.get("symbol")}


def track_decision_snapshot_outcomes(snapshot_id: str) -> Dict[str, Any]:
    snapshot = load_decision_snapshot(snapshot_id)
    if not snapshot:
        return {"ok": False, "reason": "snapshot_not_found", "snapshot_id": snapshot_id}
    as_of = str(snapshot.get("as_of") or "")
    selected_symbols = [str(symbol) for symbol in (snapshot.get("selected_symbols") or []) if str(symbol)]
    candidates = _candidate_map(snapshot.get("candidate_list") or [])
    rejected = _candidate_map(snapshot.get("rejected_candidates") or [])
    probability_output = dict(snapshot.get("probability_output") or {})
    saved: List[Dict[str, Any]] = []

    roles: List[tuple[str, str]] = []
    for symbol in selected_symbols:
        roles.append((symbol, "recommended"))
    for symbol in rejected:
        roles.append((symbol, "rejected"))
    ranked_symbols = [str(row.get("symbol")) for row in (snapshot.get("candidate_list") or []) if row.get("symbol")]
    for symbol in ranked_symbols[:5]:
        if symbol not in selected_symbols and symbol not in rejected:
            roles.append((symbol, "alternative"))
    if str(snapshot.get("final_decision") or "") == "no_trade":
        roles.append(("", "no_trade"))

    selected_outcomes: List[Dict[str, Any]] = []
    alternative_outcomes: List[Dict[str, Any]] = []
    for symbol, role in roles:
        if role == "no_trade":
            alternatives = []
            for alt_symbol in ranked_symbols[:10]:
                outcome = _future_outcome(alt_symbol, as_of=as_of)
                alternatives.append({"symbol": alt_symbol, "outcome": outcome})
            missed = max((_safe_float((item.get("outcome") or {}).get("return_3d")) for item in alternatives), default=0.0)
            avoided = min((_safe_float((item.get("outcome") or {}).get("return_3d")) for item in alternatives), default=0.0)
            outcome = {
                "complete": bool(alternatives),
                "missed_opportunity_return_3d": max(0.0, missed),
                "avoided_loss_return_3d": min(0.0, avoided),
                "alternatives": alternatives,
            }
            errors: List[str] = []
            symbol_for_store = None
        else:
            outcome = _future_outcome(symbol, as_of=as_of)
            prediction = probability_output.get(symbol) or candidates.get(symbol) or rejected.get(symbol) or {}
            errors = classify_prediction_error(prediction=prediction, outcome=outcome) if outcome.get("complete") else ["data_quality_issue"]
            symbol_for_store = symbol
            record = {"symbol": symbol, "outcome": outcome}
            if role == "recommended":
                selected_outcomes.append(record)
            else:
                alternative_outcomes.append(record)
        outcome_id = save_prediction_outcome(
            snapshot_id=snapshot_id,
            symbol=symbol_for_store,
            role=role,
            as_of=as_of,
            outcome=outcome,
            error_types=errors,
        )
        saved.append({"outcome_id": outcome_id, "symbol": symbol_for_store, "role": role, "error_types": errors})

    regret = analyze_regret(selected=selected_outcomes, alternatives=alternative_outcomes)
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "as_of": as_of,
        "saved": saved,
        "regret": regret,
    }
