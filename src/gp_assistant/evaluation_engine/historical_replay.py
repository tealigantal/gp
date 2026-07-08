from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd

from ..core.paths import results_dir, universe_dir
from ..decision_engine.pipeline import run_market_memory_selection
from ..providers.boards import is_mainboard
from ..providers.universe_provider import UniverseProvider
from ..selection_engine.datahub import MarketDataHub
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


def future_outcome(symbol: str, *, as_of: str, horizon: int = 5) -> Dict[str, Any]:
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


def _prediction_for_new(pick: Dict[str, Any]) -> Dict[str, Any]:
    probability = dict(pick.get("probability") or {})
    return {
        "up_probability_3d": probability.get("up_probability_3d"),
        "expected_return_3d": probability.get("expected_return_3d"),
        "drawdown_probability": probability.get("drawdown_probability"),
        "evidence": probability.get("evidence") or {},
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
    if pipeline == "new":
        prediction = _prediction_for_new(pick)
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
            "rank_score": (pick.get("ranking") or {}).get("ranking_score") if pipeline == "new" else pick.get("final_score"),
            "probability": (pick.get("probability") or {}).get("up_probability_3d") if pipeline == "new" else None,
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
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    evaluated: List[Dict[str, Any]] = []
    predictions: List[Dict[str, Any]] = []
    for rank, pick in enumerate(items, start=1):
        symbol = str(pick.get("symbol") or pick.get("code") or "")
        outcome = future_outcome(symbol, as_of=as_of)
        failure = _failure_analysis(pipeline=pipeline, pick=pick, outcome=outcome)
        if pipeline == "new" and outcome.get("complete"):
            probability = pick.get("probability") or {}
            evidence = probability.get("evidence") or {}
            predictions.append(
                {
                    "probability": probability.get("up_probability_3d"),
                    "success": bool(outcome.get("success") is True),
                    "effective_sample_size": evidence.get("effective_sample_size"),
                    "uncertainty": probability.get("uncertainty"),
                    "role": role,
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


def _evaluate_payload(payload: Dict[str, Any], *, as_of: str, pipeline: str, topn: int = 3) -> Dict[str, Any]:
    picks = _picks(payload, topn=topn)
    selected_symbols = {str(item.get("symbol") or item.get("code") or "") for item in picks}
    rejected = _rejected_candidates(payload, selected_symbols=selected_symbols, limit=max(topn * 3, 6))
    alternatives = [row for row in _candidate_pool(payload, limit=max(topn * 4, 12)) if str(row.get("symbol") or row.get("code") or "") not in selected_symbols][:topn]
    evaluated, pick_predictions = _evaluate_items(picks, as_of=as_of, pipeline=pipeline, role="recommended")
    evaluated_rejected, rejected_predictions = _evaluate_items(rejected, as_of=as_of, pipeline=pipeline, role="rejected")
    evaluated_alternatives, alternative_predictions = _evaluate_items(alternatives, as_of=as_of, pipeline=pipeline, role="alternative")
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
            top1_1d.append(_safe_float(first.get("return_1d")))
            top1_3d.append(_safe_float(first.get("return_3d")))
            top1_5d.append(_safe_float(first.get("return_5d")))
            by_day_top1.append(_safe_float(first.get("return_3d")))
            top3_3d.append(_mean([_safe_float((item.get("outcome") or {}).get("return_3d")) for item in complete_picks[:3]]) or 0.0)
            drawdowns.extend([_safe_float((item.get("outcome") or {}).get("max_drawdown")) for item in complete_picks])
            wins += sum(1 for item in complete_picks if (item.get("outcome") or {}).get("success") is True)
            complete += len(complete_picks)
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
    }


def run_historical_replay_ab(
    days: Iterable[str],
    *,
    topk: int = 3,
    max_symbols: int = 30,
    risk_profile: str = "normal",
    allow_legacy_network: bool = False,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for day in days:
        as_of = _date_iso(day)
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
        )
        rows.append(
            {
                "day": as_of,
                "universe": universe,
                "legacy": _evaluate_payload(legacy_payload, as_of=as_of, pipeline="legacy", topn=topk),
                "new": _evaluate_payload(new_payload, as_of=as_of, pipeline="new", topn=topk),
                "time_travel_policy": {
                    "daily_bars": "MarketDataHub.daily_ohlcv(as_of=T)",
                    "new_market_memory": "retrieve events with event.as_of < T only",
                    "new_outcomes": "signal builder stores only events whose forward 5-day outcome is known by T",
                    "legacy_baseline": (
                        "selection_engine.agent.run in symbols mode" if allow_legacy_network else "local historical candidate_pool rank order"
                    ),
                    "future_verification": "T+1/T+3/T+5 loaded only after recommendation artifact generation",
                },
            }
        )
    return {
        "schema": "HistoricalReplayAB.v1",
        "days": [_date_iso(day) for day in days],
        "topk": topk,
        "max_symbols": max_symbols,
        "allow_legacy_network": allow_legacy_network,
        "rows": rows,
        "metrics": {
            "legacy": _summary(rows, pipeline="legacy"),
            "new": _summary(rows, pipeline="new"),
        },
        "limitations": [
            "Universe comes from checked-in historical candidate_pool files when available; otherwise the local universe file is used.",
            "Default legacy baseline uses candidate_pool order without fabricating old candidate_score/final_score because rerunning the old engine can require provider/network data.",
            "Use --allow-legacy-network only when provider access is available and legacy network fetches are acceptable.",
            "Replay quality depends on cached daily bars covering T through T+5.",
        ],
    }


def save_replay_report(report: Dict[str, Any], *, name: str | None = None) -> Path:
    out_dir = results_dir() / "market_memory_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or "historical_replay_ab"
    path = out_dir / f"{stem}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run time-travel-safe Historical Replay AB validation.")
    parser.add_argument("--days", nargs="+", required=True, help="Historical trading days, e.g. 2026-01-12 2026-01-13")
    parser.add_argument("--topk", type=int, default=3)
    parser.add_argument("--max-symbols", type=int, default=30)
    parser.add_argument("--risk-profile", default="normal")
    parser.add_argument("--output-name", default=None)
    parser.add_argument(
        "--allow-legacy-network",
        action="store_true",
        help="Rerun the old selection engine; disabled by default to keep replay cache-only and time-travel safe.",
    )
    args = parser.parse_args(argv)
    report = run_historical_replay_ab(
        args.days,
        topk=args.topk,
        max_symbols=args.max_symbols,
        risk_profile=args.risk_profile,
        allow_legacy_network=args.allow_legacy_network,
    )
    path = save_replay_report(report, name=args.output_name)
    print(json.dumps({"ok": True, "path": str(path), "metrics": report.get("metrics")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
