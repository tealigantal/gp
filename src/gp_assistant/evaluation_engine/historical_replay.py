from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import random
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from ..core.paths import results_dir, universe_dir
from ..decision_engine.adaptive_policy import (
    initial_policy_state,
    load_policy_state,
    save_policy_state,
    update_policy_state_from_outcomes,
)
from ..decision_engine.pipeline import run_market_memory_selection
from ..providers.boards import is_mainboard
from ..providers.universe_provider import UniverseProvider
from ..selection_engine.datahub import MarketDataHub
from .historical_data import ReadOnlyHistoryStore
from .calibration import calibration_report
from .counterfactual import analyze_regret, classify_prediction_error


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _date_key(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    try:
        return pd.to_datetime(text).strftime("%Y%m%d")
    except Exception:
        return text.replace("-", "")


def _date_iso(value: str) -> str:
    key = _date_key(value)
    if len(key) == 8 and key.isdigit():
        return f"{key[:4]}-{key[4:6]}-{key[6:8]}"
    return str(value)


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _candidate_pool_path(day: str) -> Path | None:
    root = universe_dir()
    key = _date_key(day)
    candidates = [
        root / f"candidate_pool_{key}.csv",
        root / f"candidate_pool_{key}_ranked_pullback_v1.csv",
        root / f"candidate_pool_{key}_ranked_momentum_v1.csv",
        root / f"candidate_pool_{key}_ranked_defensive_v1.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def load_replay_universe(day: str, *, max_symbols: int = 30) -> Dict[str, Any]:
    path = _candidate_pool_path(day)
    symbols: List[str] = []
    source = None
    if path is not None:
        try:
            df = pd.read_csv(path)
            source = str(path)
            col = next((name for name in ["symbol", "code", "ts_code", "股票代码"] if name in df.columns), None)
            if col is None and len(df.columns) > 0:
                col = str(df.columns[0])
            if col is not None:
                symbols = [_normalize_symbol(value) for value in df[col].tolist()]
        except Exception:
            symbols = []
    if not symbols:
        provider = UniverseProvider()
        symbols = provider.get_symbols()
        source = str(provider.last_meta().get("source") or "universe:file")
    cleaned: List[str] = []
    seen: set[str] = set()
    for symbol in symbols:
        if symbol and symbol not in seen and is_mainboard(symbol):
            seen.add(symbol)
            cleaned.append(symbol)
        if len(cleaned) >= max_symbols:
            break
    return {
        "day": _date_iso(day),
        "source": source,
        "symbols": cleaned,
        "count": len(cleaned),
        "max_symbols": max_symbols,
    }


def future_outcome(
    symbol: str,
    *,
    as_of: str,
    horizon: int = 5,
    pick: Dict[str, Any] | None = None,
    data_source: Any | None = None,
    friction_bps: float = 30.0,
) -> Dict[str, Any]:
    if data_source is not None and hasattr(data_source, "future_outcome"):
        return data_source.future_outcome(
            dict(pick or {"symbol": symbol}),
            as_of=as_of,
            horizon=horizon,
            friction_bps=friction_bps,
        )
    hub = MarketDataHub()
    try:
        df, meta = hub.daily_ohlcv(symbol, as_of=None, min_len=80, prefer_cache_only=True)
    except Exception as ex:  # noqa: BLE001
        return {"complete": False, "reason": f"daily_data_unavailable:{type(ex).__name__}", "symbol": symbol}
    if df is None or df.empty or "date" not in df.columns:
        return {"complete": False, "reason": "daily_data_missing", "symbol": symbol, "data_meta": meta}
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    target = pd.to_datetime(as_of).normalize()
    matches = work.index[work["date"].dt.normalize() == target]
    if len(matches) == 0:
        return {"complete": False, "reason": "as_of_not_found", "symbol": symbol, "data_meta": meta}
    idx = int(matches[0])
    if idx + horizon >= len(work):
        return {"complete": False, "reason": "future_window_not_available", "symbol": symbol, "data_meta": meta}
    entry = _safe_float(work["close"].iloc[idx])
    if entry <= 0:
        return {"complete": False, "reason": "entry_price_invalid", "symbol": symbol, "data_meta": meta}
    fwd = work.iloc[idx + 1 : idx + horizon + 1]
    closes = pd.to_numeric(fwd["close"], errors="coerce")
    highs = pd.to_numeric(fwd["high"], errors="coerce") if "high" in fwd.columns else closes
    lows = pd.to_numeric(fwd["low"], errors="coerce") if "low" in fwd.columns else closes
    ret1 = _safe_float(closes.iloc[0] / entry - 1.0)
    ret3 = _safe_float(closes.iloc[min(2, len(closes) - 1)] / entry - 1.0)
    ret5 = _safe_float(closes.iloc[min(4, len(closes) - 1)] / entry - 1.0)
    return {
        "complete": True,
        "symbol": symbol,
        "entry_date": pd.to_datetime(as_of).date().isoformat(),
        "entry_close": entry,
        "return_1d": ret1,
        "return_3d": ret3,
        "return_5d": ret5,
        "max_profit": _safe_float(highs.max() / entry - 1.0),
        "max_drawdown": _safe_float(lows.min() / entry - 1.0),
        "success": bool(ret3 > 0.0),
        "matured_at": pd.to_datetime(fwd["date"].iloc[-1]).date().isoformat(),
        "data_meta": {"source": meta.get("source"), "len": meta.get("len")},
    }


def _picks(payload: Dict[str, Any], *, topn: int) -> List[Dict[str, Any]]:
    rows = list(payload.get("picks") or [])
    return [dict(row) for row in rows if row.get("symbol") or row.get("code")][:topn]


def _candidate_pool(payload: Dict[str, Any], *, limit: int) -> List[Dict[str, Any]]:
    rows = list(payload.get("candidate_pool") or [])
    return [dict(row) for row in rows if row.get("symbol") or row.get("code")][:limit]


def _rejected_candidates(payload: Dict[str, Any], *, selected_symbols: set[str], limit: int) -> List[Dict[str, Any]]:
    rows = list(payload.get("rejected_candidates") or [])
    if not rows:
        rows = [row for row in _candidate_pool(payload, limit=limit * 3) if str(row.get("symbol") or row.get("code") or "") not in selected_symbols]
    return [dict(row) for row in rows if row.get("symbol") or row.get("code")][:limit]


def _prediction_for_new(pick: Dict[str, Any], *, use_adaptive: bool = True) -> Dict[str, Any]:
    probability = dict(pick.get("probability") or {})
    adaptive = dict(pick.get("adaptive_policy") or {})
    calibrated = adaptive.get("calibrated_probability") if adaptive.get("calibrated_probability") is not None else pick.get("calibrated_probability")
    raw_probability = probability.get("up_probability_3d")
    probability_value = calibrated if use_adaptive and calibrated is not None else raw_probability
    return {
        "probability": probability_value,
        "raw_probability": raw_probability,
        "up_probability_3d": probability_value,
        "calibrated_probability": calibrated if use_adaptive else None,
        "expected_return_3d": probability.get("expected_return_3d"),
        "drawdown_probability": probability.get("drawdown_probability"),
        "evidence": probability.get("evidence") or {},
        "adaptive_score": adaptive.get("adaptive_score") if adaptive else pick.get("adaptive_score"),
        "recommendation_strength": adaptive.get("recommendation_strength") if adaptive else pick.get("recommendation_strength"),
        "expert_contributions": adaptive.get("expert_contributions") if adaptive else pick.get("expert_contributions"),
        "feature_coverage": adaptive.get("feature_coverage") if adaptive else pick.get("feature_coverage"),
    }


def _legacy_payload_from_universe(universe: Dict[str, Any], *, topk: int) -> Dict[str, Any]:
    rows = [
        {
            "symbol": symbol,
            "rank": idx,
            "source_rank": idx,
            "legacy_baseline_source": "historical_candidate_pool",
            "candidate_score": None,
            "champion": None,
            "final_score": None,
        }
        for idx, symbol in enumerate(list(universe.get("symbols") or []), start=1)
    ]
    return {
        "tradeable": bool(rows),
        "decision": "recommend" if rows else "no_trade",
        "picks": rows[:topk],
        "candidate_pool": rows,
        "legacy_baseline": {
            "source": "historical_candidate_pool",
            "universe_source": universe.get("source"),
            "score_fields": "not_recomputed",
            "reason": "AB replay defaults to local, time-travel-safe candidate-pool order because old selection_engine fetches live/provider data when rerun.",
        },
    }


def _run_legacy_baseline(
    *,
    as_of: str,
    topk: int,
    symbols: List[str],
    universe: Dict[str, Any],
    risk_profile: str,
    allow_network: bool,
) -> Dict[str, Any]:
    if not allow_network:
        return _legacy_payload_from_universe(universe, topk=topk)
    from ..selection_engine.agent import run as run_legacy_selection

    return run_legacy_selection(date=as_of, topk=topk, universe="symbols", symbols=symbols, risk_profile=risk_profile)


def _failure_analysis(*, pipeline: str, pick: Dict[str, Any], outcome: Dict[str, Any]) -> Dict[str, Any]:
    if pipeline in {"new", "adaptive", "main"}:
        prediction = _prediction_for_new(pick, use_adaptive=pipeline != "main")
        errors = classify_prediction_error(prediction=prediction, outcome=outcome)
        evidence = prediction.get("evidence") or {}
        if outcome.get("complete") and outcome.get("success") is False and _safe_float(evidence.get("effective_sample_size")) < 30:
            errors.append("insufficient_evidence")
        if outcome.get("complete") and outcome.get("success") is False and _safe_float(prediction.get("up_probability_3d"), 0.5) >= 0.60:
            errors.append("probability_overconfidence")
    else:
        errors = []
        if outcome.get("complete") and outcome.get("success") is False:
            errors.append("wrong_signal")
        if not outcome.get("complete"):
            errors.append("data_quality_issue")
    return {
        "prediction": {
            "pipeline": pipeline,
            "symbol": pick.get("symbol") or pick.get("code"),
            "rank_score": (pick.get("ranking") or {}).get("ranking_score") if pipeline in {"new", "adaptive", "main"} else pick.get("final_score"),
            "probability": (_prediction_for_new(pick, use_adaptive=pipeline != "main").get("probability") if pipeline in {"new", "adaptive", "main"} else None),
            "raw_probability": (_prediction_for_new(pick, use_adaptive=pipeline != "main").get("raw_probability") if pipeline in {"new", "adaptive", "main"} else None),
            "adaptive_score": (_prediction_for_new(pick).get("adaptive_score") if pipeline in {"new", "adaptive"} else None),
            "recommendation_strength": (_prediction_for_new(pick).get("recommendation_strength") if pipeline in {"new", "adaptive"} else None),
            "feature_coverage": (_prediction_for_new(pick).get("feature_coverage") if pipeline in {"new", "adaptive"} else None),
        },
        "actual": outcome,
        "error_type": sorted(set(errors)),
    }


def _evaluate_items(
    items: List[Dict[str, Any]],
    *,
    as_of: str,
    pipeline: str,
    role: str,
    data_source: Any | None = None,
    friction_bps: float = 30.0,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    evaluated: List[Dict[str, Any]] = []
    predictions: List[Dict[str, Any]] = []
    for rank, pick in enumerate(items, start=1):
        symbol = str(pick.get("symbol") or pick.get("code") or "")
        outcome = future_outcome(
            symbol,
            as_of=as_of,
            pick=pick,
            data_source=data_source,
            friction_bps=friction_bps,
        )
        failure = _failure_analysis(pipeline=pipeline, pick=pick, outcome=outcome)
        if pipeline in {"new", "adaptive", "main"} and outcome.get("complete"):
            probability = pick.get("probability") or {}
            evidence = probability.get("evidence") or {}
            prediction = _prediction_for_new(pick, use_adaptive=pipeline != "main")
            predictions.append(
                {
                    "probability": prediction.get("probability"),
                    "raw_probability": prediction.get("raw_probability"),
                    "success": bool(outcome.get("success") is True),
                    "effective_sample_size": evidence.get("effective_sample_size"),
                    "uncertainty": probability.get("uncertainty"),
                    "role": role,
                    "adaptive_score": prediction.get("adaptive_score"),
                    "recommendation_strength": prediction.get("recommendation_strength"),
                    "feature_coverage": prediction.get("feature_coverage"),
                    "expert_contributions": prediction.get("expert_contributions"),
                }
            )
        evaluated.append({"rank": rank, "role": role, "pick": pick, "outcome": outcome, "failure_analysis": failure})
    return evaluated, predictions


def _no_trade_outcome(*, decision: str, selected: List[Dict[str, Any]], alternatives: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    if decision not in {"observe", "no_trade"} and selected:
        return None
    complete = [item for item in alternatives if (item.get("outcome") or {}).get("complete")]
    returns = [_safe_float((item.get("outcome") or {}).get("return_3d")) for item in complete]
    if not complete:
        return {
            "decision": decision,
            "alternative_count": 0,
            "avoided_loss": False,
            "missed_opportunity": False,
            "reason": "no_complete_alternative_outcomes",
        }
    best_return = max(returns)
    avg_return = _mean(returns)
    return {
        "decision": decision,
        "alternative_count": len(complete),
        "best_alternative_return_3d": best_return,
        "average_alternative_return_3d": avg_return,
        "avoided_loss": bool(best_return <= 0.0),
        "missed_opportunity": bool(best_return > 0.0),
    }


def _evaluate_payload(
    payload: Dict[str, Any],
    *,
    as_of: str,
    pipeline: str,
    topn: int = 3,
    data_source: Any | None = None,
    friction_bps: float = 30.0,
) -> Dict[str, Any]:
    picks = _picks(payload, topn=topn)
    selected_symbols = {str(item.get("symbol") or item.get("code") or "") for item in picks}
    rejected = _rejected_candidates(payload, selected_symbols=selected_symbols, limit=max(topn * 3, 6))
    alternatives = [row for row in _candidate_pool(payload, limit=max(topn * 4, 12)) if str(row.get("symbol") or row.get("code") or "") not in selected_symbols][:topn]
    evaluated, pick_predictions = _evaluate_items(
        picks,
        as_of=as_of,
        pipeline=pipeline,
        role="recommended",
        data_source=data_source,
        friction_bps=friction_bps,
    )
    evaluated_rejected, rejected_predictions = _evaluate_items(
        rejected,
        as_of=as_of,
        pipeline=pipeline,
        role="rejected",
        data_source=data_source,
        friction_bps=friction_bps,
    )
    evaluated_alternatives, alternative_predictions = _evaluate_items(
        alternatives,
        as_of=as_of,
        pipeline=pipeline,
        role="alternative",
        data_source=data_source,
        friction_bps=friction_bps,
    )
    decision = payload.get("decision") or ("recommend" if payload.get("picks") else "no_trade")
    return {
        "pipeline": pipeline,
        "as_of": as_of,
        "tradeable": bool(payload.get("tradeable")),
        "decision": decision,
        "snapshot_id": payload.get("decision_context_snapshot_id"),
        "evaluated_picks": evaluated,
        "evaluated_rejected": evaluated_rejected,
        "evaluated_alternatives": evaluated_alternatives,
        "regret": analyze_regret(selected=evaluated, alternatives=evaluated_alternatives),
        "no_trade_outcome": _no_trade_outcome(decision=str(decision), selected=evaluated, alternatives=evaluated_alternatives),
        "calibration_predictions": pick_predictions + rejected_predictions + alternative_predictions,
    }


def _mean(values: Sequence[float]) -> float | None:
    clean = [float(value) for value in values if value == value]
    return None if not clean else float(sum(clean) / len(clean))


def _max_consecutive_losses(day_returns: Sequence[float]) -> int:
    longest = 0
    current = 0
    for value in day_returns:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _portfolio_max_drawdown(day_returns: Sequence[float], *, concurrent_batches: int = 3) -> float | None:
    if not day_returns:
        return None
    equity = 1.0
    peak = 1.0
    worst = 0.0
    allocation = 1.0 / max(1, int(concurrent_batches))
    for value in day_returns:
        equity *= 1.0 + float(value) * allocation
        peak = max(peak, equity)
        worst = min(worst, equity / peak - 1.0)
    return float(worst)


def _adaptive_score_bucket(value: Any) -> str:
    score = _safe_float(value, -1.0)
    if score < 0.0:
        return "missing"
    if score < 0.40:
        return "lt_0.40"
    if score < 0.55:
        return "0.40_0.55"
    if score < 0.70:
        return "0.55_0.70"
    return "gte_0.70"


def _performance_rows(items: List[Dict[str, Any]], *, key: str) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        outcome = item.get("outcome") or {}
        if not outcome.get("complete"):
            continue
        pick = item.get("pick") or {}
        adaptive = dict(pick.get("adaptive_policy") or {})
        if key == "adaptive_score_bucket":
            group = _adaptive_score_bucket(adaptive.get("adaptive_score") or pick.get("adaptive_score"))
        else:
            group = str(adaptive.get("recommendation_strength") or pick.get("recommendation_strength") or "missing")
        groups.setdefault(group, []).append(item)
    rows: List[Dict[str, Any]] = []
    for group, scoped in sorted(groups.items()):
        returns = [_safe_float((item.get("outcome") or {}).get("return_3d")) for item in scoped]
        drawdowns = [_safe_float((item.get("outcome") or {}).get("max_drawdown")) for item in scoped]
        wins = sum(1 for item in scoped if (item.get("outcome") or {}).get("success") is True)
        rows.append(
            {
                "group": group,
                "count": len(scoped),
                "return_3d_avg": _mean(returns),
                "max_drawdown_avg": _mean(drawdowns),
                "win_rate": float(wins / max(1, len(scoped))),
            }
        )
    return rows


def _quality_cohort_rows(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        outcome = dict(item.get("outcome") or {})
        if not outcome.get("complete"):
            continue
        pick = dict(item.get("pick") or {})
        adaptive = dict(pick.get("adaptive_policy") or {})
        risk_flags = list((pick.get("risk") or {}).get("risk_flags") or pick.get("risk_flags") or [])
        missing = list(adaptive.get("missing_features") or pick.get("missing_features") or [])
        labels = []
        if risk_flags:
            labels.append("risk_flagged")
        if missing:
            labels.append("optional_data_missing")
        if not labels:
            labels.append("clean")
        for label in labels:
            groups.setdefault(label, []).append(item)
    strength_values = {"exploratory": 0.0, "cautious": 1.0, "normal": 2.0, "strong": 3.0}
    rows: List[Dict[str, Any]] = []
    for group, scoped in sorted(groups.items()):
        raw_returns = [_safe_float((item.get("outcome") or {}).get("return_3d")) for item in scoped]
        net_returns = [
            float((item.get("outcome") or {}).get("net_return_3d"))
            for item in scoped
            if (item.get("outcome") or {}).get("filled") is True
            and (item.get("outcome") or {}).get("net_return_3d") is not None
        ]
        adaptive_scores = [
            _safe_float(((item.get("pick") or {}).get("adaptive_policy") or {}).get("adaptive_score"), 0.0)
            for item in scoped
        ]
        strengths = [
            strength_values.get(
                str(((item.get("pick") or {}).get("adaptive_policy") or {}).get("recommendation_strength") or ""),
                0.0,
            )
            for item in scoped
        ]
        rows.append(
            {
                "group": group,
                "count": len(scoped),
                "filled_count": len(net_returns),
                "return_3d_avg": _mean(raw_returns),
                "net_return_3d_avg": _mean(net_returns),
                "adaptive_score_avg": _mean(adaptive_scores),
                "recommendation_strength_avg": _mean(strengths),
            }
        )
    return rows


def _current_main_math_payload(adaptive_payload: Dict[str, Any], *, topk: int) -> Dict[str, Any]:
    ranked = list(adaptive_payload.get("candidate_pool") or [])
    top = ranked[0] if ranked else None
    decision = "no_trade"
    reason = "no_candidates"
    picks: List[Dict[str, Any]] = []
    if top is not None:
        probability = dict(top.get("probability") or {})
        evidence = dict(probability.get("evidence") or {})
        risk = dict(top.get("risk") or {})
        effective_n = _safe_float(evidence.get("effective_sample_size"), 0.0)
        drawdown = _safe_float(risk.get("drawdown_probability") or probability.get("drawdown_probability"), 1.0)
        if effective_n < 10.0:
            reason = "effective_sample_too_small"
        elif effective_n < 30.0:
            decision, reason = "observe", "effective_sample_low"
        elif (
            _safe_float(probability.get("up_probability_3d"), 0.0) >= 0.55
            and _safe_float(probability.get("expected_return_3d"), 0.0) > 0.0
            and drawdown < 0.45
            and _safe_float((top.get("ranking") or {}).get("ranking_score"), 0.0) > 0.0
        ):
            decision, reason = "recommend", "math_rank_supports_top_candidate"
            picks = [dict(top)]
        else:
            decision, reason = "observe", "math_edge_not_strong_enough"
    return {
        "as_of": adaptive_payload.get("as_of"),
        "tradeable": bool(decision == "recommend" and picks),
        "decision": decision,
        "reason": reason,
        "picks": picks[: max(1, int(topk))],
        "candidate_pool": ranked,
        "rejected_candidates": [dict(item) for item in ranked if not picks or item.get("symbol") != picks[0].get("symbol")],
        "baseline": {"source": "main_6637d41_deterministic_math_policy", "llm_used": False},
    }


def _summary(rows: List[Dict[str, Any]], *, pipeline: str) -> Dict[str, Any]:
    by_day_top1: List[float] = []
    top1_1d: List[float] = []
    top1_3d: List[float] = []
    top1_5d: List[float] = []
    top3_3d: List[float] = []
    drawdowns: List[float] = []
    wins = 0
    complete = 0
    predictions: List[Dict[str, Any]] = []
    adaptive_evaluated: List[Dict[str, Any]] = []
    decision_counts: Dict[str, int] = {}
    rejected_returns: List[float] = []
    rejected_wins = 0
    rejected_complete = 0
    alternative_returns: List[float] = []
    regrets: List[float] = []
    no_trade_count = 0
    avoided_loss_count = 0
    missed_opportunity_count = 0
    no_trade_best_alt: List[float] = []
    top1_net_3d: List[float] = []
    top3_net_3d: List[float] = []
    filled_pick_count = 0
    for row in rows:
        payload = row.get(pipeline) or {}
        decision = str(payload.get("decision") or "unknown")
        decision_counts[decision] = decision_counts.get(decision, 0) + 1
        scoped = payload.get("evaluated_picks") or []
        complete_picks = [item for item in scoped if (item.get("outcome") or {}).get("complete")]
        if not complete_picks:
            pass
        else:
            first = complete_picks[0]["outcome"]
            adaptive_evaluated.extend(complete_picks)
            top1_1d.append(_safe_float(first.get("return_1d")))
            top1_3d.append(_safe_float(first.get("return_3d")))
            top1_5d.append(_safe_float(first.get("return_5d")))
            by_day_top1.append(_safe_float(first.get("return_3d")))
            top3_3d.append(_mean([_safe_float((item.get("outcome") or {}).get("return_3d")) for item in complete_picks[:3]]) or 0.0)
            drawdowns.extend([_safe_float((item.get("outcome") or {}).get("max_drawdown")) for item in complete_picks])
            wins += sum(1 for item in complete_picks if (item.get("outcome") or {}).get("success") is True)
            complete += len(complete_picks)
            filled_returns = [
                float((item.get("outcome") or {}).get("net_return_3d"))
                for item in complete_picks[:3]
                if (item.get("outcome") or {}).get("filled") is True
                and (item.get("outcome") or {}).get("net_return_3d") is not None
            ]
            filled_pick_count += len(filled_returns)
            if filled_returns:
                top1_net_3d.append(filled_returns[0])
                top3_net_3d.append(float(sum(filled_returns) / len(filled_returns)))
        for item in payload.get("evaluated_rejected") or []:
            outcome = item.get("outcome") or {}
            if not outcome.get("complete"):
                continue
            rejected_returns.append(_safe_float(outcome.get("return_3d")))
            rejected_wins += 1 if outcome.get("success") is True else 0
            rejected_complete += 1
        for item in payload.get("evaluated_alternatives") or []:
            outcome = item.get("outcome") or {}
            if outcome.get("complete"):
                alternative_returns.append(_safe_float(outcome.get("return_3d")))
        regret = payload.get("regret") or {}
        if "regret" in regret:
            regrets.append(_safe_float(regret.get("regret")))
        no_trade = payload.get("no_trade_outcome")
        if no_trade:
            no_trade_count += 1
            if no_trade.get("avoided_loss"):
                avoided_loss_count += 1
            if no_trade.get("missed_opportunity"):
                missed_opportunity_count += 1
            if no_trade.get("best_alternative_return_3d") is not None:
                no_trade_best_alt.append(_safe_float(no_trade.get("best_alternative_return_3d")))
        predictions.extend(payload.get("calibration_predictions") or [])
    return {
        "days_with_outcomes": len(by_day_top1),
        "coverage": float(len(by_day_top1) / max(1, len(rows))),
        "decision_counts": decision_counts,
        "top1_return_1d_avg": _mean(top1_1d),
        "top1_return_3d_avg": _mean(top1_3d),
        "top1_return_5d_avg": _mean(top1_5d),
        "top3_return_3d_avg": _mean(top3_3d),
        "max_drawdown_min": min(drawdowns) if drawdowns else None,
        "max_consecutive_top1_losses_3d": _max_consecutive_losses(by_day_top1),
        "win_rate": float(wins / max(1, complete)),
        "precision": float(wins / max(1, complete)),
        "evaluated_pick_count": complete,
        "filled_pick_count": filled_pick_count,
        "top1_net_return_3d_avg": _mean(top1_net_3d),
        "top3_net_return_3d_avg": _mean(top3_net_3d),
        "portfolio_max_drawdown": _portfolio_max_drawdown(top3_net_3d),
        "portfolio_model": "equal_weight_top3_one_third_capital_per_overlapping_3d_batch",
        "rejected_return_3d_avg": _mean(rejected_returns),
        "rejected_win_rate": float(rejected_wins / max(1, rejected_complete)),
        "rejected_evaluated_count": rejected_complete,
        "alternative_return_3d_avg": _mean(alternative_returns),
        "average_regret_3d": _mean(regrets),
        "no_trade_days": no_trade_count,
        "no_trade_avoided_loss_days": avoided_loss_count,
        "no_trade_missed_opportunity_days": missed_opportunity_count,
        "no_trade_best_alternative_3d_avg": _mean(no_trade_best_alt),
        "calibration": calibration_report(predictions) if predictions else {"sample_size": 0, "brier_score": None, "buckets": []},
        "adaptive_score_bucket_performance": _performance_rows(adaptive_evaluated, key="adaptive_score_bucket"),
        "recommendation_strength_performance": _performance_rows(adaptive_evaluated, key="recommendation_strength"),
        "exploratory_picks_performance": [
            row for row in _performance_rows(adaptive_evaluated, key="recommendation_strength") if row.get("group") == "exploratory"
        ],
        "cautious_picks_performance": [
            row for row in _performance_rows(adaptive_evaluated, key="recommendation_strength") if row.get("group") == "cautious"
        ],
        "data_quality_cohort_performance": _quality_cohort_rows(adaptive_evaluated),
    }


def run_historical_replay_ab(
    days: Iterable[str],
    *,
    topk: int = 3,
    max_symbols: int = 30,
    risk_profile: str = "normal",
    allow_legacy_network: bool = False,
    update_policy_state: bool = False,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    policy_state = load_policy_state() if update_policy_state else None
    pending_updates: List[Dict[str, Any]] = []
    for day in days:
        as_of = _date_iso(day)
        if update_policy_state and policy_state is not None:
            matured = [item for item in pending_updates if str(item.get("matured_at") or "") <= as_of]
            pending_updates = [item for item in pending_updates if str(item.get("matured_at") or "") > as_of]
            for item in matured:
                policy_state = update_policy_state_from_outcomes(policy_state, list(item.get("records") or []))
            if matured:
                save_policy_state(policy_state)
        universe = load_replay_universe(as_of, max_symbols=max_symbols)
        symbols = list(universe.get("symbols") or [])
        if not symbols:
            rows.append({"day": as_of, "universe": universe, "error": "empty_universe"})
            continue
        legacy_payload = _run_legacy_baseline(
            as_of=as_of,
            topk=topk,
            symbols=symbols,
            universe=universe,
            risk_profile=risk_profile,
            allow_network=allow_legacy_network,
        )
        new_payload = run_market_memory_selection(
            date=as_of,
            topk=topk,
            risk_profile=risk_profile,
            symbols=symbols,
            prefer_cache_only=True,
            policy_state=policy_state,
        )
        new_evaluated = _evaluate_payload(new_payload, as_of=as_of, pipeline="new", topn=topk)
        if update_policy_state and policy_state is not None:
            records = [
                *list(new_evaluated.get("evaluated_picks") or []),
                *list(new_evaluated.get("evaluated_rejected") or []),
                *list(new_evaluated.get("evaluated_alternatives") or []),
            ]
            grouped: Dict[str, List[Dict[str, Any]]] = {}
            for record in records:
                matured_at = str((record.get("outcome") or {}).get("matured_at") or "")
                if matured_at:
                    grouped.setdefault(matured_at, []).append(record)
            pending_updates.extend({"matured_at": key, "records": value} for key, value in sorted(grouped.items()))
        rows.append(
            {
                "day": as_of,
                "universe": universe,
                "legacy": _evaluate_payload(legacy_payload, as_of=as_of, pipeline="legacy", topn=topk),
                "new": new_evaluated,
                "time_travel_policy": {
                    "daily_bars": "MarketDataHub.daily_ohlcv(as_of=T)",
                    "new_market_memory": "retrieve events with event.as_of < T only",
                    "new_outcomes": "signal builder stores only events whose forward 5-day outcome is known by T",
                    "legacy_baseline": (
                        "selection_engine.agent.run in symbols mode" if allow_legacy_network else "local historical candidate_pool rank order"
                    ),
                    "future_verification": "T+1/T+3/T+5 loaded only after recommendation artifact generation",
                    "policy_update": "outcomes affect policy only when matured_at <= next replay as_of",
                },
            }
        )
    return {
        "schema": "HistoricalReplayAB.v1",
        "days": [_date_iso(day) for day in days],
        "topk": topk,
        "max_symbols": max_symbols,
        "allow_legacy_network": allow_legacy_network,
        "update_policy_state": update_policy_state,
        "pending_policy_update_batches": len(pending_updates),
        "rows": rows,
        "metrics": {
            "legacy": _summary(rows, pipeline="legacy"),
            "new": _summary(rows, pipeline="new"),
        },
        "limitations": [
            "Universe comes from checked-in historical candidate_pool files when available; otherwise the local universe file is used.",
            "Default legacy baseline uses candidate_pool order without fabricating old candidate_score/final_score because rerunning the old engine can require provider/network data.",
            "Use --allow-legacy-network only when provider access is available and legacy network fetches are acceptable.",
            "Adaptive policy updates are queued until their T+5 matured_at date is visible to the replay clock.",
            "Replay quality depends on cached daily bars covering T through T+5.",
        ],
    }


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append_jsonl(path: Path, item: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _rewrite_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8")


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _daily_net_return(row: Dict[str, Any], pipeline: str) -> float:
    evaluated = list((row.get(pipeline) or {}).get("evaluated_picks") or [])[:3]
    values = [
        float((item.get("outcome") or {}).get("net_return_3d"))
        for item in evaluated
        if (item.get("outcome") or {}).get("filled") is True
        and (item.get("outcome") or {}).get("net_return_3d") is not None
    ]
    return float(sum(values) / len(values)) if values else 0.0


def _bootstrap_delta_ci(rows: List[Dict[str, Any]], *, samples: int = 2000, seed: int = 20260711) -> Dict[str, Any]:
    deltas = [_daily_net_return(row, "adaptive") - _daily_net_return(row, "main") for row in rows]
    if not deltas:
        return {"count": 0, "mean": None, "lower_95": None, "upper_95": None, "samples": samples, "seed": seed}
    rng = random.Random(seed)
    means: List[float] = []
    count = len(deltas)
    for _ in range(max(1, int(samples))):
        means.append(sum(deltas[rng.randrange(count)] for _ in range(count)) / count)
    means.sort()
    lower = means[max(0, int(len(means) * 0.025) - 1)]
    upper = means[min(len(means) - 1, int(len(means) * 0.975))]
    return {
        "count": count,
        "mean": float(sum(deltas) / count),
        "lower_95": float(lower),
        "upper_95": float(upper),
        "samples": samples,
        "seed": seed,
    }


def _split_rows(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    valid = [row for row in rows if row.get("valid_for_metrics") is True]
    first = int(len(valid) * 0.60)
    second = int(len(valid) * 0.80)
    return {"development": valid[:first], "validation": valid[first:second], "holdout": valid[second:]}


def _strength_direction_is_reasonable(metrics: Dict[str, Any]) -> bool:
    order = {"exploratory": 0, "cautious": 1, "normal": 2, "strong": 3}
    rows = [
        row
        for row in (metrics.get("recommendation_strength_performance") or [])
        if int(row.get("count") or 0) >= 50 and row.get("return_3d_avg") is not None
    ]
    rows.sort(key=lambda row: order.get(str(row.get("group")), -1))
    return all(
        float(right["return_3d_avg"]) >= float(left["return_3d_avg"]) - 0.003
        for left, right in zip(rows, rows[1:])
    )


def _quality_direction_is_reasonable(metrics: Dict[str, Any]) -> bool:
    rows = {str(row.get("group")): row for row in (metrics.get("data_quality_cohort_performance") or [])}
    clean = rows.get("clean")
    if not clean or int(clean.get("count") or 0) < 50:
        return True
    clean_strength = _safe_float(clean.get("recommendation_strength_avg"), 0.0)
    for label in ("risk_flagged", "optional_data_missing"):
        scoped = rows.get(label)
        if scoped and int(scoped.get("count") or 0) >= 50:
            if _safe_float(scoped.get("recommendation_strength_avg"), 0.0) > clean_strength + 0.10:
                return False
    return True


def _acceptance_report(holdout: List[Dict[str, Any]], *, friction_bps: float = 30.0) -> Dict[str, Any]:
    adaptive = _summary(holdout, pipeline="adaptive")
    baseline = _summary(holdout, pipeline="main")
    delta = _bootstrap_delta_ci(holdout)
    adaptive_brier = (adaptive.get("calibration") or {}).get("brier_score")
    baseline_brier = (baseline.get("calibration") or {}).get("brier_score")
    adaptive_drawdown = adaptive.get("portfolio_max_drawdown")
    baseline_drawdown = baseline.get("portfolio_max_drawdown")
    checks = {
        "holdout_days_gte_250": len(holdout) >= 250,
        "filled_picks_gte_500": int(adaptive.get("filled_pick_count") or 0) >= 500,
        "top1_net_return_positive": _safe_float(adaptive.get("top1_net_return_3d_avg"), -1.0) > 0.0,
        "top3_net_return_positive": _safe_float(adaptive.get("top3_net_return_3d_avg"), -1.0) > 0.0,
        "delta_ci_noninferior": delta.get("lower_95") is not None and float(delta["lower_95"]) >= -0.003,
        "portfolio_drawdown_lte_10pct": adaptive_drawdown is not None and float(adaptive_drawdown) >= -0.10,
        "drawdown_vs_main_within_2pct": (
            adaptive_drawdown is not None
            and (baseline_drawdown is None or float(adaptive_drawdown) >= float(baseline_drawdown) - 0.02)
        ),
        "brier_lte_0_25": adaptive_brier is not None and float(adaptive_brier) <= 0.25,
        "brier_vs_main_within_0_01": (
            adaptive_brier is not None
            and (baseline_brier is None or float(adaptive_brier) <= float(baseline_brier) + 0.01)
        ),
        "strength_groups_direction_reasonable": _strength_direction_is_reasonable(adaptive),
        "risk_and_missing_groups_direction_reasonable": _quality_direction_is_reasonable(adaptive),
        "all_rows_data_complete": all(row.get("valid_for_metrics") is True and not row.get("error") for row in holdout),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "adaptive": adaptive,
        "main": baseline,
        "adaptive_minus_main_bootstrap": delta,
        "policy": {
            "friction_bps": float(friction_bps),
            "noninferiority_margin": -0.003,
            "max_portfolio_drawdown": -0.10,
            "max_drawdown_deterioration": -0.02,
            "max_brier": 0.25,
            "max_brier_deterioration": 0.01,
        },
    }


def run_full_history_replay(
    *,
    history_db: str | Path,
    start: str | None = None,
    end: str | None = None,
    topk: int = 3,
    max_symbols: int = 200,
    min_history: int = 120,
    min_universe: int = 100,
    friction_bps: float = 30.0,
    mode: str = "static",
    checkpoint_dir: str | Path,
    resume: bool = False,
    data_source: ReadOnlyHistoryStore | None = None,
) -> Dict[str, Any]:
    if mode not in {"static", "causal-adaptive"}:
        raise ValueError("mode must be static or causal-adaptive")
    checkpoint_root = Path(checkpoint_dir).resolve()
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    rows_path = checkpoint_root / "rows.jsonl"
    state_path = checkpoint_root / "state.json"
    if not resume and rows_path.exists():
        rows_path.unlink()
    rows = _load_jsonl(rows_path) if resume else []
    state_payload: Dict[str, Any] = {}
    if resume and state_path.exists():
        try:
            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state_payload = {}
    if resume:
        checkpoint_day = str(state_payload.get("last_completed_day") or "")
        consistent_rows = [row for row in rows if checkpoint_day and str(row.get("day") or "") <= checkpoint_day]
        if len(consistent_rows) != len(rows):
            rows = consistent_rows
            _rewrite_jsonl(rows_path, rows)
    completed_days = {str(row.get("day")) for row in rows}
    policy_state = dict(state_payload.get("policy_state") or initial_policy_state())
    pending_updates = list(state_payload.get("pending_updates") or [])
    memory_seeded = bool(state_payload.get("memory_seeded", bool(rows)))
    owned_source = data_source is None
    cache_symbols = max(512, int(max_symbols) * 3) if int(max_symbols) > 0 else 0
    source = data_source or ReadOnlyHistoryStore(history_db, frame_cache_symbols=cache_symbols)
    days = source.trading_days(start=start, end=end)
    if hasattr(source, "prepare_market_index") and days:
        calendar = source.trading_days(end=end)
        first_index = calendar.index(days[0]) if days[0] in calendar else 0
        context_days = calendar[max(0, first_index - 120) :]
        source.prepare_market_index(context_days, min_history=min_history, rank_limit=max_symbols)
    market_context_cache: Dict[str, Dict[str, Any]] = {}

    def historical_context(day: str) -> Dict[str, Any]:
        key = _date_iso(day)
        cached = market_context_cache.get(key)
        if cached is not None:
            return cached
        scoped_symbols = source.eligible_symbols(key, min_history=min_history, limit=0)
        if len(scoped_symbols) < int(min_universe):
            context = {
                "as_of": key,
                "grade": "C",
                "market_regime": "C",
                "regime_reasons": ["eligible_universe_below_minimum"],
                "raw": {"breadth_count": len(scoped_symbols)},
                "hard_block": True,
                "hard_block_reasons": ["eligible_universe_below_minimum"],
            }
        else:
            context = source.market_context(key, None, min_history=min_history)
        market_context_cache[key] = context
        return context

    previous_memory_root = os.environ.get("GP_MARKET_MEMORY_DIR")
    os.environ["GP_MARKET_MEMORY_DIR"] = str(checkpoint_root / "events")
    try:
        for day in days:
            as_of = _date_iso(day)
            if as_of in completed_days:
                continue
            if mode == "causal-adaptive":
                matured = [item for item in pending_updates if str(item.get("matured_at") or "") <= as_of]
                pending_updates = [item for item in pending_updates if str(item.get("matured_at") or "") > as_of]
                for item in matured:
                    policy_state = update_policy_state_from_outcomes(policy_state, list(item.get("records") or []))
            eligible_symbols = source.eligible_symbols(as_of, min_history=min_history, limit=0)
            symbols = source.rank_universe(as_of, eligible_symbols, limit=max_symbols)
            if len(eligible_symbols) < int(min_universe):
                row = {
                    "day": as_of,
                    "universe": {
                        "eligible_count": len(eligible_symbols),
                        "evaluated_count": len(symbols),
                        "min_required": min_universe,
                        "source": "history_db_read_only",
                    },
                    "valid_for_metrics": False,
                    "error": "eligible_universe_below_minimum",
                }
            else:
                market_context = historical_context(as_of)
                adaptive_payload = run_market_memory_selection(
                    date=as_of,
                    topk=topk,
                    risk_profile="normal",
                    symbols=symbols,
                    prefer_cache_only=True,
                    allow_snapshot=False,
                    data_source=source,
                    market_context_override=market_context,
                    policy_state=policy_state,
                    historical_market_context_resolver=historical_context,
                    historical_event_mode="newly_matured" if memory_seeded else "window",
                )
                memory_seeded = True
                main_payload = _current_main_math_payload(adaptive_payload, topk=topk)
                adaptive_evaluated = _evaluate_payload(
                    adaptive_payload,
                    as_of=as_of,
                    pipeline="adaptive",
                    topn=topk,
                    data_source=source,
                    friction_bps=friction_bps,
                )
                main_evaluated = _evaluate_payload(
                    main_payload,
                    as_of=as_of,
                    pipeline="main",
                    topn=topk,
                    data_source=source,
                    friction_bps=friction_bps,
                )
                selected = list(adaptive_evaluated.get("evaluated_picks") or [])
                complete_count = sum(1 for item in selected if (item.get("outcome") or {}).get("complete") is True)
                completeness = float(complete_count / max(1, len(selected)))
                row = {
                    "day": as_of,
                    "universe": {
                        "eligible_count": len(eligible_symbols),
                        "evaluated_count": len(symbols),
                        "min_history": min_history,
                        "source": "history_db_read_only",
                        "history_db": str(Path(history_db).resolve()),
                    },
                    "market_context": market_context,
                    "main": main_evaluated,
                    "adaptive": adaptive_evaluated,
                    "outcome_completeness": completeness,
                    "valid_for_metrics": bool(selected and completeness >= 0.95),
                    "time_travel_policy": {
                        "selection_data": "item_time <= as_of",
                        "network": "disabled",
                        "market_context": "same-day historical breadth",
                        "policy_update": "T+5 outcomes applied only when matured_at <= replay clock",
                    },
                }
                if mode == "causal-adaptive":
                    records = [
                        *list(adaptive_evaluated.get("evaluated_picks") or []),
                        *list(adaptive_evaluated.get("evaluated_rejected") or []),
                        *list(adaptive_evaluated.get("evaluated_alternatives") or []),
                    ]
                    grouped: Dict[str, List[Dict[str, Any]]] = {}
                    for record in records:
                        matured_at = str((record.get("outcome") or {}).get("matured_at") or "")
                        if matured_at:
                            grouped.setdefault(matured_at, []).append(record)
                    pending_updates.extend({"matured_at": key, "records": value} for key, value in sorted(grouped.items()))
            rows.append(row)
            completed_days.add(as_of)
            _append_jsonl(rows_path, row)
            _write_json_atomic(
                state_path,
                {
                    "last_completed_day": as_of,
                    "mode": mode,
                    "policy_state": policy_state,
                    "pending_updates": pending_updates,
                    "memory_seeded": memory_seeded,
                },
            )
    finally:
        if previous_memory_root is None:
            os.environ.pop("GP_MARKET_MEMORY_DIR", None)
        else:
            os.environ["GP_MARKET_MEMORY_DIR"] = previous_memory_root
        if owned_source:
            source.close()

    splits = _split_rows(rows)
    split_metrics = {
        name: {"main": _summary(scoped, pipeline="main"), "adaptive": _summary(scoped, pipeline="adaptive")}
        for name, scoped in splits.items()
    }
    acceptance = _acceptance_report(splits["holdout"], friction_bps=friction_bps)
    return {
        "schema": "FullHistoricalReplay.v1",
        "history_db": str(Path(history_db).resolve()),
        "date_range": {"start": start, "end": end},
        "mode": mode,
        "topk": topk,
        "max_symbols": max_symbols,
        "min_history": min_history,
        "min_universe": min_universe,
        "friction_bps": friction_bps,
        "rows": rows,
        "split_counts": {name: len(scoped) for name, scoped in splits.items()},
        "metrics": split_metrics,
        "acceptance": acceptance,
        "checkpoint": {"directory": str(checkpoint_root), "rows": str(rows_path), "state": str(state_path)},
        "limitations": [
            "Historical universe is reconstructed from symbols present in the local history DB and may have survivorship bias.",
            "Daily-bar execution uses conservative stop-first ordering when stop and take-profit are both touched.",
            "Causal-adaptive mode is evaluation-only; production remains on fixed policy state for this rollout.",
            "Backtest results are validation evidence, not a guarantee of live returns.",
        ],
    }


def save_replay_report(
    report: Dict[str, Any],
    *,
    name: str | None = None,
    output_dir: str | Path | None = None,
) -> Path:
    out_dir = Path(output_dir).resolve() if output_dir else results_dir() / "market_memory_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or "historical_replay_ab"
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run time-travel-safe Historical Replay AB validation.")
    parser.add_argument("--days", nargs="+", help="Historical trading days, e.g. 2026-01-12 2026-01-13")
    parser.add_argument("--history-db", help="Read-only history.db path for full-market replay.")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--max-symbols", type=int, default=30)
    parser.add_argument("--full-max-symbols", type=int, default=200, help="Production-like liquidity prefilter size; 0 scores all eligible symbols.")
    parser.add_argument("--min-history", type=int, default=120)
    parser.add_argument("--min-universe", type=int, default=100)
    parser.add_argument("--friction-bps", type=float, default=30.0)
    parser.add_argument("--mode", choices=["static", "causal-adaptive"], default="static")
    parser.add_argument("--checkpoint-dir", default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--offline", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--risk-profile", default="normal")
    parser.add_argument("--output-name", default=None)
    parser.add_argument(
        "--allow-legacy-network",
        action="store_true",
        help="Rerun the old selection engine; disabled by default to keep replay cache-only and time-travel safe.",
    )
    parser.add_argument(
        "--update-policy-state",
        action="store_true",
        help="After each day's outcomes are evaluated, update and save the adaptive policy state.",
    )
    args = parser.parse_args(argv)
    if args.history_db:
        if not args.offline:
            parser.error("full history replay is offline-only")
        checkpoint_dir = args.checkpoint_dir or str(results_dir() / "market_memory_validation" / "full_replay_checkpoint")
        report = run_full_history_replay(
            history_db=args.history_db,
            start=args.start,
            end=args.end,
            topk=args.topk,
            max_symbols=args.full_max_symbols,
            min_history=args.min_history,
            min_universe=args.min_universe,
            friction_bps=args.friction_bps,
            mode=args.mode,
            checkpoint_dir=checkpoint_dir,
            resume=args.resume,
        )
    else:
        if not args.days:
            parser.error("provide --days or --history-db")
        report = run_historical_replay_ab(
            args.days,
            topk=args.topk,
            max_symbols=args.max_symbols,
            risk_profile=args.risk_profile,
            allow_legacy_network=args.allow_legacy_network,
            update_policy_state=args.update_policy_state,
        )
    path = save_replay_report(report, name=args.output_name, output_dir=args.output_dir)
    print(json.dumps({"ok": True, "path": str(path), "metrics": report.get("metrics")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
