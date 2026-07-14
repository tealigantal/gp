from __future__ import annotations

import json
import math
import random
from bisect import bisect_left
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from statistics import mean, stdev
from typing import Any, Dict, Iterable, List, Mapping

import pandas as pd

from ..core.config import load_config
from ..decision_engine.serenity_policy import (
    counterfactual_arm_checksum,
    freeze_risk_plan,
    reference_input_checksum,
    reference_learning_sample_id,
)
from ..market_memory.store import load_decision_snapshot
from ..runtime.market_clock import next_trading_day_on_or_after
from ..runtime.utils import now_iso
from ..selection_engine.datahub import MarketDataHub
from .models import NATIVE_SERENITY_FORMULA_VERSION, SerenityPolicyState
from .scheduler import trading_day_cooldown_until
from .store import (
    commit_evaluation_result,
    list_evaluations,
    list_pending_evaluations,
    load_policy_state,
    load_reference_snapshot,
    recent_poll_outcomes,
    save_policy_state_with_ledger,
)


EVALUATION_FORMULA_VERSION = "SerenityEvaluation.v1"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def _clip(value: Any, lo: float, hi: float) -> float:
    parsed = _safe_float(value)
    return lo if parsed < lo else hi if parsed > hi else parsed


def _entry_fill(row: pd.Series, risk: Mapping[str, Any]) -> float | None:
    entry = dict(risk.get("entry") or {})
    open_price = _safe_float(row.get("open"), 0.0)
    low = _safe_float(row.get("low"), open_price)
    high = _safe_float(row.get("high"), open_price)
    exact = _safe_float(entry.get("price") or entry.get("trigger_price"), 0.0)
    band_low = _safe_float(entry.get("low") or entry.get("entry_low"), exact)
    band_high = _safe_float(entry.get("high") or entry.get("entry_high"), exact)
    if exact > 0 and low <= exact <= high:
        return min(open_price, exact) if open_price > 0 else exact
    if band_low > 0 and band_high >= band_low and low <= band_high and high >= band_low:
        if band_low <= open_price <= band_high:
            return open_price
        return band_high
    return None


def _exit_return(future: pd.DataFrame, *, fill: float, risk: Mapping[str, Any], days: int, friction_bps: float) -> tuple[float, str]:
    stop = dict(risk.get("stop") or {})
    take = dict(risk.get("take_profit") or {})
    stop_price = _safe_float(stop.get("price") or stop.get("stop_price"), 0.0)
    targets = list(take.get("targets") or []) if isinstance(take.get("targets"), list) else []
    first_target = targets[0] if targets else take.get("price") or take.get("take1")
    if isinstance(first_target, dict):
        first_target = first_target.get("price")
    take_price = _safe_float(first_target, 0.0)
    selected = future.iloc[: max(1, min(days, len(future)))]
    exit_price = _safe_float(selected["close"].iloc[-1], fill)
    reason = f"t{days}_close"
    for _, row in selected.iterrows():
        low = _safe_float(row.get("low"), 0.0)
        high = _safe_float(row.get("high"), 0.0)
        if stop_price > 0 and low <= stop_price:
            exit_price, reason = stop_price, "stop_first_conservative"
            break
        if take_price > 0 and high >= take_price:
            exit_price, reason = take_price, "take_profit"
            break
    return float(exit_price / fill - 1.0 - friction_bps / 10000.0), reason


def future_outcome(
    symbol: str,
    *,
    as_of: str,
    risk: Mapping[str, Any],
    data_source: Any | None = None,
    friction_bps: float = 30.0,
) -> Dict[str, Any]:
    hub = data_source or MarketDataHub()
    try:
        df, meta = hub.daily_ohlcv(symbol, as_of=None, min_len=120, prefer_cache_only=True)
    except Exception as ex:  # noqa: BLE001
        return {"complete": False, "reason": f"daily_data_unavailable:{type(ex).__name__}", "symbol": symbol}
    if df is None or df.empty or "date" not in df.columns:
        return {"complete": False, "reason": "daily_data_missing", "symbol": symbol, "data_meta": meta}
    frame = df.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    target = pd.to_datetime(as_of).normalize()
    dates = frame["date"].dt.normalize().tolist()
    pos = bisect_left(dates, target)
    if pos >= len(dates) or dates[pos] != target:
        return {"complete": False, "reason": "as_of_not_found", "symbol": symbol, "data_meta": meta}
    if pos + 5 >= len(frame):
        return {"complete": False, "reason": "future_window_not_available", "symbol": symbol, "data_meta": meta}
    future = frame.iloc[pos + 1 : pos + 6]
    required = future[[column for column in ("open", "high", "low", "close") if column in future.columns]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    if len(required.columns) < 4 or required.isna().any().any() or bool(meta.get("strict_blocked")):
        return {"complete": False, "reason": "t5_window_not_finalized", "symbol": symbol, "data_meta": meta}
    matured_at = pd.to_datetime(future["date"].iloc[-1]).date().isoformat()
    fill = _entry_fill(future.iloc[0], risk)
    if fill is None or fill <= 0:
        return {
            "complete": True,
            "symbol": symbol,
            "matured_at": matured_at,
            "filled": False,
            "net_return_3d": 0.0,
            "net_return_5d": 0.0,
            "max_drawdown": 0.0,
            "exit_reason_3d": "not_filled",
            "exit_reason_5d": "not_filled",
            "friction_bps": friction_bps,
            "data_meta": meta,
            "t5_finalized": True,
        }
    net3, reason3 = _exit_return(future, fill=fill, risk=risk, days=3, friction_bps=friction_bps)
    net5, reason5 = _exit_return(future, fill=fill, risk=risk, days=5, friction_bps=friction_bps)
    lows = pd.to_numeric(future["low"], errors="coerce")
    return {
        "complete": True,
        "symbol": symbol,
        "matured_at": matured_at,
        "filled": True,
        "fill_price": fill,
        "net_return_3d": net3,
        "net_return_5d": net5,
        "max_drawdown": _safe_float(lows.min() / fill - 1.0),
        "exit_reason_3d": reason3,
        "exit_reason_5d": reason5,
        "friction_bps": friction_bps,
        "data_meta": meta,
        "t5_finalized": True,
    }


def _arm_utility(selected: Iterable[str], outcomes: Mapping[str, Dict[str, Any]], baseline: set[str]) -> Dict[str, Any]:
    symbols = list(selected)
    rows = [outcomes[symbol] for symbol in symbols]
    per_symbol = [
        _clip(row.get("net_return_3d"), -0.10, 0.10)
        + 0.25 * _clip(row.get("net_return_5d"), -0.10, 0.10)
        + 0.50 * _clip(row.get("max_drawdown"), -0.10, 0.0)
        for row in rows
    ]
    turnover_delta = len(set(symbols).symmetric_difference(baseline)) / max(1, len(baseline))
    utility = mean(per_symbol) - 0.001 * turnover_delta if per_symbol else 0.0
    return {
        "utility": float(utility),
        "mean_net_return_3d": mean([_safe_float(row.get("net_return_3d")) for row in rows]) if rows else 0.0,
        "mean_net_return_5d": mean([_safe_float(row.get("net_return_5d")) for row in rows]) if rows else 0.0,
        "max_drawdown": min([_safe_float(row.get("max_drawdown")) for row in rows], default=0.0),
        "turnover_delta": float(turnover_delta),
        "filled_count": sum(1 for row in rows if row.get("filled") is True),
        "selected_symbols": symbols,
    }


def _terminal_integrity_evaluation(
    pending: Mapping[str, Any],
    errors: Iterable[str],
    *,
    reference_snapshot_id: str | None = None,
) -> Dict[str, Any]:
    unique_errors = list(dict.fromkeys(str(error) for error in errors if str(error)))
    payload = {
        "decision_day": str(pending.get("decision_day") or ""),
        "matured_at": str(pending.get("decision_day") or ""),
        "epoch": int(pending.get("epoch") or 1),
        "formula_version": EVALUATION_FORMULA_VERSION,
        "addon_formula_version": str(pending.get("formula_version") or ""),
        "input_hash": str(pending.get("input_hash") or ""),
        "reference_snapshot_id": reference_snapshot_id
        or str(pending.get("reference_snapshot_id") or ""),
        "decision_context_snapshot_id": pending.get("decision_context_snapshot_id"),
        "outcomes": {},
        "arms": {},
        "learning_eligible": False,
        "available_results": 0,
        "supportive_count": 0,
        "conflicting_count": 0,
        "integrity_errors": unique_errors,
        "created_at": now_iso(),
    }
    payload["evaluation_id"] = "sereval_" + sha256(
        (
            f"integrity|{payload['reference_snapshot_id']}|{payload['epoch']}|"
            f"{'|'.join(unique_errors)}"
        ).encode()
    ).hexdigest()[:24]
    return payload


def evaluate_pending_item(pending: Mapping[str, Any], *, data_source: Any | None = None, today: date | None = None) -> Dict[str, Any] | None:
    try:
        reference = load_reference_snapshot(str(pending.get("reference_snapshot_id") or ""))
    except Exception as ex:  # noqa: BLE001
        return _terminal_integrity_evaluation(
            pending,
            [f"reference_snapshot_unreadable:{type(ex).__name__}"],
        )
    if reference is None:
        return _terminal_integrity_evaluation(pending, ["reference_snapshot_missing"])
    try:
        decision = load_decision_snapshot(str(pending.get("decision_context_snapshot_id") or ""))
    except Exception as ex:  # noqa: BLE001
        decision = None
        decision_load_error = f"decision_snapshot_unreadable:{type(ex).__name__}"
    else:
        decision_load_error = None
    integrity_errors: List[str] = []
    recomputed_learning_sample_id = reference_learning_sample_id(
        decision_day=reference.decision_day,
        signals=reference.signals,
        arms=reference.counterfactual_arms,
        risk_plans=reference.risk_plans,
    )
    recomputed_checksum = reference_input_checksum(
        decision_context_snapshot_id=reference.decision_context_snapshot_id,
        decision_day=reference.decision_day,
        decision_at=reference.decision_at,
        signals=reference.signals,
        arms=reference.counterfactual_arms,
        reference_arms=reference.reference_counterfactual_arms,
        risk_plans=reference.risk_plans,
        learning_sample_id=reference.learning_sample_id,
        actual_weight=reference.actual_weight,
        policy_state=reference.policy_state,
        baseline_selected_symbols=reference.baseline_selected_symbols,
        applied_selected_symbols=reference.applied_selected_symbols,
        would_change_topk=reference.would_change_topk,
    )
    if recomputed_learning_sample_id != reference.learning_sample_id:
        integrity_errors.append("learning_sample_id_mismatch")
    if recomputed_checksum != reference.input_checksum:
        integrity_errors.append("reference_content_checksum_mismatch")
    if reference.input_checksum != str(pending.get("input_hash") or ""):
        integrity_errors.append("reference_input_hash_mismatch")
    if reference.decision_context_snapshot_id != str(pending.get("decision_context_snapshot_id") or ""):
        integrity_errors.append("reference_decision_snapshot_mismatch")
    if reference.decision_day != str(pending.get("decision_day") or ""):
        integrity_errors.append("reference_decision_day_mismatch")
    if not decision:
        integrity_errors.append("decision_snapshot_missing")
        if decision_load_error:
            integrity_errors.append(decision_load_error)
    elif str(decision.get("snapshot_id") or "") != str(pending.get("decision_context_snapshot_id") or ""):
        integrity_errors.append("decision_snapshot_identity_mismatch")
    if decision and str(decision.get("decision_trade_day") or "") != str(
        pending.get("decision_day") or ""
    ):
        integrity_errors.append("decision_day_mismatch")
    if int(pending.get("epoch") or 0) <= 0:
        integrity_errors.append("epoch_invalid")
    if str(pending.get("formula_version") or "") != NATIVE_SERENITY_FORMULA_VERSION:
        integrity_errors.append("formula_version_mismatch")
    arms = list(reference.counterfactual_arms or [])
    if [round(float(arm.weight), 2) for arm in arms] != [step / 100 for step in range(9)]:
        integrity_errors.append("counterfactual_arm_set_invalid")
    for arm in arms:
        if counterfactual_arm_checksum(arm) != arm.checksum:
            integrity_errors.append(f"counterfactual_arm_checksum_mismatch:{arm.weight:.2f}")
        if arm.selected_symbols != arm.ranked_symbols[: len(arm.selected_symbols)]:
            integrity_errors.append(f"counterfactual_selection_order_invalid:{arm.weight:.2f}")
        if any(not math.isfinite(_safe_float(value, float("nan"))) for value in arm.scores.values()):
            integrity_errors.append(f"counterfactual_score_non_finite:{arm.weight:.2f}")
    union = sorted({symbol for arm in arms for symbol in arm.selected_symbols})
    decision_risk_output = dict(
        (decision or {}).get("serenity_outcome_risk_plans")
        or (decision or {}).get("risk_output")
        or {}
    )
    for symbol in union:
        frozen_plan = reference.risk_plans.get(symbol)
        if frozen_plan is None:
            integrity_errors.append(f"frozen_risk_plan_missing:{symbol}")
            continue
        if decision and freeze_risk_plan(decision_risk_output.get(symbol)) != dict(frozen_plan):
            integrity_errors.append(f"decision_risk_plan_mismatch:{symbol}")
    if integrity_errors:
        return _terminal_integrity_evaluation(
            pending,
            integrity_errors,
            reference_snapshot_id=reference.snapshot_id,
        )
    outcomes: Dict[str, Dict[str, Any]] = {}
    for symbol in union:
        outcome = future_outcome(
            symbol,
            as_of=str(pending.get("decision_day") or ""),
            risk=dict(reference.risk_plans.get(symbol) or {}),
            data_source=data_source,
        )
        if outcome.get("complete") is not True:
            return None
        if outcome.get("t5_finalized") is not True:
            return None
        outcomes[symbol] = outcome
    matured_at = max(str(outcome.get("matured_at") or "") for outcome in outcomes.values())
    if not matured_at:
        return None
    current_day = today or datetime.now(timezone.utc).date()
    eligible_day = next_trading_day_on_or_after(date.fromisoformat(matured_at) + timedelta(days=1))
    if eligible_day is None or current_day < datetime.strptime(eligible_day, "%Y%m%d").date():
        return None
    baseline_symbols = set(arms[0].selected_symbols)
    arm_results: Dict[str, Dict[str, Any]] = {}
    baseline_utility = 0.0
    for arm in arms:
        result = _arm_utility(arm.selected_symbols, outcomes, baseline_symbols)
        if abs(float(arm.weight)) < 1e-12:
            baseline_utility = float(result["utility"])
        arm_results[f"{float(arm.weight):.2f}"] = result
    for result in arm_results.values():
        result["delta"] = _clip(float(result["utility"]) - baseline_utility, -0.05, 0.05)
    available = [signal for signal in reference.signals.values() if signal.availability == 1]
    learning_available = [signal for signal in available if signal.learning_eligible]
    payload = {
        "decision_day": str(pending.get("decision_day") or ""),
        "matured_at": matured_at,
        "epoch": int(pending.get("epoch") or 1),
        "formula_version": EVALUATION_FORMULA_VERSION,
        "addon_formula_version": str(pending.get("formula_version") or ""),
        "input_hash": str(pending.get("input_hash") or ""),
        "reference_snapshot_id": reference.snapshot_id,
        "learning_sample_id": reference.learning_sample_id or reference.snapshot_id,
        "decision_context_snapshot_id": pending.get("decision_context_snapshot_id"),
        "outcomes": outcomes,
        "arms": arm_results,
        "learning_eligible": bool(learning_available),
        "learning_fact_ids": sorted(
            {fact_id for signal in learning_available for fact_id in signal.fact_ids}
        ),
        "available_results": len(learning_available),
        "supportive_count": sum(1 for signal in learning_available if signal.direction > 0),
        "conflicting_count": sum(1 for signal in learning_available if signal.direction < 0),
        "integrity_errors": integrity_errors,
        "created_at": now_iso(),
    }
    payload["evaluation_id"] = "sereval_" + sha256(
        json.dumps(
            {
                "reference": reference.snapshot_id,
                "epoch": payload["epoch"],
                "formula": payload["formula_version"],
                "input": payload["input_hash"],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    return payload


def _bootstrap_ci(values: List[float], *, seed: int, samples: int = 2000) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        means.append(mean(values[rng.randrange(len(values))] for _ in values))
    means.sort()
    return means[int(0.025 * (len(means) - 1))], means[int(0.975 * (len(means) - 1))]


def _metrics(evaluations: List[Dict[str, Any]], weight: float) -> Dict[str, Any]:
    key = f"{weight:.2f}"
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for evaluation in evaluations:
        day = str(evaluation.get("decision_day") or "")
        arm = dict((evaluation.get("arms") or {}).get(key) or {})
        baseline = dict((evaluation.get("arms") or {}).get("0.00") or {})
        if not day or not arm or not baseline:
            continue
        by_day.setdefault(day, []).append(
            {
                "delta": _safe_float(arm.get("delta")),
                "mdd_worsening": max(
                    0.0,
                    _safe_float(baseline.get("max_drawdown")) - _safe_float(arm.get("max_drawdown")),
                ),
                "turnover_delta": _safe_float(arm.get("turnover_delta")),
            }
        )
    daily_rows = [
        {
            "decision_day": day,
            "delta": mean(item["delta"] for item in rows),
            "mdd_worsening": max(item["mdd_worsening"] for item in rows),
            "turnover_delta": mean(item["turnover_delta"] for item in rows),
        }
        for day, rows in sorted(by_day.items())
    ]
    deltas = [float(row["delta"]) for row in daily_rows]
    lcb, ucb = _bootstrap_ci(deltas, seed=20260711 + int(weight * 100)) if deltas else (0.0, 0.0)
    mdd_worsening = max((float(row["mdd_worsening"]) for row in daily_rows), default=0.0)
    turnover = mean([float(row["turnover_delta"]) for row in daily_rows]) if daily_rows else 0.0
    standard_error = stdev(deltas) / math.sqrt(len(deltas)) if len(deltas) > 1 else 0.0
    windows = []
    for idx in range(0, len(deltas), 10):
        chunk = deltas[idx : idx + 10]
        if chunk:
            windows.append(mean(chunk))
    return {
        "weight": weight,
        "count": len(deltas),
        "mean_delta": mean(deltas) if deltas else 0.0,
        "lcb95": lcb,
        "ucb95": ucb,
        "standard_error": standard_error,
        "mdd_worsening": mdd_worsening,
        "turnover_delta": turnover,
        "positive_10d_windows": sum(1 for value in windows[-4:] if value > 0),
        "window_count": len(windows[-4:]),
    }


def _transition_hash(state: SerenityPolicyState, *, new_state: str, new_weight: float, reason: str) -> str:
    raw = f"{state.transition_log_hash}|{state.epoch}|{state.state}|{state.applied_weight}|{new_state}|{new_weight}|{reason}|{now_iso()}"
    return sha256(raw.encode()).hexdigest()


def _dedupe_learning_evaluations(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(
            row.get("learning_sample_id")
            or row.get("reference_snapshot_id")
            or row.get("evaluation_id")
            or ""
        )
        if not key:
            continue
        unique.setdefault(key, row)
    return list(unique.values())


def _suspend(state: SerenityPolicyState, reasons: List[str]) -> SerenityPolicyState:
    now = datetime.now(timezone.utc)
    return state.model_copy(
        update={
            "state": "suspended",
            "previous_weight": state.applied_weight,
            "applied_weight": 0.0,
            "state_since": now.isoformat(),
            "cooldown_until": trading_day_cooldown_until(now, trading_days=10),
            "suspension_reasons": list(dict.fromkeys(reasons)),
            "consecutive_passes": 0,
            "transition_log_hash": _transition_hash(state, new_state="suspended", new_weight=0.0, reason=";".join(reasons)),
        }
    )


def update_policy_from_evaluations(state: SerenityPolicyState, evaluations: List[Dict[str, Any]]) -> SerenityPolicyState:
    cfg = load_config().serenity
    all_epoch_rows = [row for row in evaluations if int(row.get("epoch") or 0) == state.epoch]
    integrity_errors = [
        str(error)
        for row in all_epoch_rows
        for error in list(row.get("integrity_errors") or [])
        if str(error)
    ] if state.state != "suspended" else []
    current_epoch = _dedupe_learning_evaluations(
        row for row in all_epoch_rows if row.get("learning_eligible") is True
    )
    matured_days = len({str(row.get("decision_day") or "") for row in current_epoch})
    available_results = sum(int(row.get("available_results") or 0) for row in current_epoch)
    supportive_count = sum(int(row.get("supportive_count") or 0) for row in current_epoch)
    conflicting_count = sum(int(row.get("conflicting_count") or 0) for row in current_epoch)
    recent_polls = recent_poll_outcomes("cninfo", limit=20)
    source_success = (
        mean([
            1.0
            if bool(row.get("complete")) and str(row.get("status") or "") == "success"
            else 0.0
            for row in recent_polls
        ])
        if recent_polls
        else 0.0
    )
    time_field_complete_rate = (
        1.0
        if recent_polls and all(bool(row.get("complete")) for row in recent_polls)
        else source_success
    )
    all_decision_days = sorted({str(row.get("decision_day") or "") for row in current_epoch if str(row.get("decision_day") or "")})
    window_day_set = set(all_decision_days[-max(20, cfg.eval_window_days) :])
    window = [row for row in current_epoch if str(row.get("decision_day") or "") in window_day_set]
    metrics = {f"{weight/100:.2f}": _metrics(window, weight / 100.0) for weight in range(0, 9)}
    updates: Dict[str, Any] = {
        "matured_days": matured_days,
        "available_results": available_results,
        "decision_snapshots": len(current_epoch),
        "supportive_count": supportive_count,
        "conflicting_count": conflicting_count,
        "rolling_metrics": {
            "arms": metrics,
            "last_evaluation_count": len(current_epoch),
            "last_policy_evaluated_matured_days": matured_days,
            "last_policy_evaluated_day": max(all_decision_days, default=None),
        },
        "source_health": {
            "recent_complete_rate": source_success,
            "time_field_complete_rate": time_field_complete_rate,
            "poll_count": len(recent_polls),
        },
        "last_matured_day": max((str(row.get("matured_at") or "") for row in current_epoch), default=state.last_matured_day),
        "last_evaluation_at": now_iso(),
    }
    state = state.model_copy(update=updates)
    current_metrics = metrics.get(f"{state.applied_weight:.2f}") or metrics["0.00"]
    last20_day_set = set(all_decision_days[-20:])
    last20 = [row for row in current_epoch if str(row.get("decision_day") or "") in last20_day_set]
    last20_metrics = _metrics(last20, state.applied_weight) if last20 else current_metrics
    hard_reasons: List[str] = []
    if integrity_errors:
        hard_reasons.extend(integrity_errors)
    if not math.isfinite(float(state.applied_weight)) or state.applied_weight < 0 or state.applied_weight > 0.08:
        hard_reasons.append("weight_non_finite_or_out_of_bounds")
    if state.state in {"probation", "active"}:
        if last20_metrics["count"] >= 20 and last20_metrics["mean_delta"] <= -0.003:
            hard_reasons.append("top3_delta_below_minus_30bp")
        if last20_metrics["count"] >= 20 and last20_metrics["ucb95"] < 0:
            hard_reasons.append("delta_ucb_below_zero")
        if current_metrics["mdd_worsening"] >= 0.02:
            hard_reasons.append("mdd_worsening_ge_2pp")
        last10_day_set = set(all_decision_days[-10:])
        last10 = [
            row
            for row in current_epoch
            if str(row.get("decision_day") or "") in last10_day_set
        ]
        last10_metrics = _metrics(last10, state.applied_weight) if last10 else current_metrics
        if last10_metrics["turnover_delta"] > 0.25 and last10_metrics["count"] >= 10:
            hard_reasons.append("turnover_delta_gt_25pct")
    if hard_reasons:
        return _suspend(state, hard_reasons)

    if state.state == "warming":
        if not state.bootstrap_run_id:
            return state.model_copy(update={"applied_weight": 0.0})
        return state.model_copy(
            update={"state": "shadow", "state_since": now_iso(), "applied_weight": 0.0}
        )
    if state.state == "shadow":
        arm_candidates = [metrics["0.01"], metrics["0.02"]]
        arm_pass = any(
            row["mean_delta"] > 0
            and row["lcb95"] >= 0
            and row["mdd_worsening"] <= 0.005
            and row["turnover_delta"] <= 0.10
            and row["window_count"] >= 4
            and row["positive_10d_windows"] >= 3
            for row in arm_candidates
        )
        data_gate = (
            bool(state.bootstrap_run_id)
            and matured_days >= 40
            and available_results >= 300
            and len(current_epoch) >= 100
            and supportive_count >= 30
            and conflicting_count >= 30
            and source_success >= 0.98
            and time_field_complete_rate >= 0.99
        )
        if data_gate and arm_pass:
            return state.model_copy(
                update={
                    "state": "probation",
                    "previous_weight": 0.0,
                    "applied_weight": 0.01,
                    "state_since": now_iso(),
                    "probation_matured_days": 0,
                    "probation_available_results": 0,
                    "consecutive_passes": 0,
                    "transition_log_hash": _transition_hash(state, new_state="probation", new_weight=0.01, reason="shadow_gates_passed"),
                }
            )
        return state

    since = str(state.state_since or "")
    since_rows = [row for row in current_epoch if str(row.get("created_at") or "") >= since]
    probation_days = len({str(row.get("decision_day") or "") for row in since_rows})
    probation_results = sum(int(row.get("available_results") or 0) for row in since_rows)
    state = state.model_copy(update={"probation_matured_days": probation_days, "probation_available_results": probation_results})
    if state.state == "probation":
        row = _metrics(since_rows, state.applied_weight)
        passed = row["mean_delta"] >= 0.001 and row["lcb95"] >= 0 and row["mdd_worsening"] <= 0.005 and row["turnover_delta"] <= 0.10
        consecutive = state.consecutive_passes + 1 if passed else 0
        failures = state.consecutive_failures + 1 if row["mean_delta"] < 0 else 0
        state = state.model_copy(
            update={
                "consecutive_passes": consecutive,
                "consecutive_failures": failures,
            }
        )
        if probation_days >= 40 and probation_results >= 300 and consecutive >= 4:
            return state.model_copy(
                update={
                    "state": "active",
                    "previous_weight": state.applied_weight,
                    "applied_weight": 0.02,
                    "state_since": now_iso(),
                    "consecutive_passes": 0,
                    "consecutive_failures": 0,
                    "transition_log_hash": _transition_hash(state, new_state="active", new_weight=0.02, reason="probation_gates_passed"),
                }
            )
        return state
    if state.state == "active":
        eligible = [
            row
            for key, row in sorted(metrics.items())
            if float(key) > 0
            and float(key) <= state.max_weight
            and row["mean_delta"] >= 0.001
            and row["lcb95"] >= 0
            and row["mdd_worsening"] <= 0.005
            and row["turnover_delta"] <= 0.10
        ]
        if eligible:
            best = max(eligible, key=lambda row: (float(row["mean_delta"]), -float(row["weight"])))
            one_se_floor = float(best["mean_delta"]) - float(best.get("standard_error") or 0.0)
            target = min(
                float(row["weight"])
                for row in eligible
                if float(row["mean_delta"]) >= one_se_floor
            )
        else:
            target = 0.0
        current = state.applied_weight
        if target > current:
            passes = state.consecutive_passes + 1
            if passes >= 2:
                new_weight = min(state.max_weight, current + 0.01)
                return state.model_copy(
                    update={
                        "previous_weight": current,
                        "applied_weight": round(new_weight, 2),
                        "consecutive_passes": 0,
                        "transition_log_hash": _transition_hash(state, new_state="active", new_weight=new_weight, reason="active_increase"),
                    }
                )
            return state.model_copy(update={"consecutive_passes": passes})
        if target < current:
            new_weight = max(0.0, current - 0.01)
            return state.model_copy(
                update={
                    "previous_weight": current,
                    "applied_weight": round(new_weight, 2),
                    "consecutive_passes": 0,
                    "transition_log_hash": _transition_hash(state, new_state="active", new_weight=new_weight, reason="active_decrease"),
                }
            )
        return state.model_copy(update={"consecutive_passes": 0})
    if state.state == "suspended":
        clean = [row for row in since_rows if not list(row.get("integrity_errors") or [])]
        cooldown = datetime.fromisoformat(state.cooldown_until) if state.cooldown_until else datetime.max.replace(tzinfo=timezone.utc)
        clean_days = len({str(row.get("decision_day") or "") for row in clean if str(row.get("decision_day") or "")})
        if (
            datetime.now(timezone.utc) >= cooldown
            and source_success >= 0.90
            and clean_days >= 20
            and sum(int(row.get("available_results") or 0) for row in clean) >= 100
        ):
            next_epoch = state.epoch + 1
            return state.model_copy(
                update={
                    "epoch": next_epoch,
                    "state": "shadow",
                    "previous_weight": 0.0,
                    "applied_weight": 0.0,
                    "state_since": now_iso(),
                    "matured_days": 0,
                    "available_results": 0,
                    "decision_snapshots": 0,
                    "supportive_count": 0,
                    "conflicting_count": 0,
                    "consecutive_failures": 0,
                    "consecutive_passes": 0,
                    "suspension_reasons": [],
                    "cooldown_until": None,
                    "rolling_metrics": {},
                    "transition_log_hash": _transition_hash(state, new_state="shadow", new_weight=0.0, reason="suspension_recovery"),
                }
            )
    return state


def process_pending_evaluations(*, data_source: Any | None = None, today: date | None = None) -> Dict[str, Any]:
    pending = list_pending_evaluations(limit=200)
    saved: List[str] = []
    for item in pending:
        payload = evaluate_pending_item(item, data_source=data_source, today=today)
        if payload is None:
            continue
        evaluation_id, inserted = commit_evaluation_result(
            payload=payload,
            pending_id=str(item.get("pending_id") or ""),
        )
        if inserted:
            saved.append(evaluation_id)
    state = load_policy_state()
    evaluations = list_evaluations(epoch=state.epoch, limit=2000)
    eligible_evaluations = [row for row in evaluations if row.get("learning_eligible") is True]
    matured_days = len(
        {
            str(row.get("decision_day") or "")
            for row in eligible_evaluations
            if str(row.get("decision_day") or "")
        }
    )
    previous_matured_days = int((state.rolling_metrics or {}).get("last_policy_evaluated_matured_days") or 0)
    previous_evaluated_day = str((state.rolling_metrics or {}).get("last_policy_evaluated_day") or "")
    eligible_days = sorted(
        {
            str(row.get("decision_day") or "")
            for row in eligible_evaluations
            if str(row.get("decision_day") or "")
        }
    )
    if previous_evaluated_day:
        new_eligible_days = [day for day in eligible_days if day > previous_evaluated_day]
        enough_new_mature_days = len(new_eligible_days) >= load_config().serenity.update_mature_days
    else:
        enough_new_mature_days = (
            matured_days - previous_matured_days >= load_config().serenity.update_mature_days
        )
    immediate_integrity_failure = state.state != "suspended" and any(
        list(row.get("integrity_errors") or []) for row in evaluations
    )
    should_update = (
        enough_new_mature_days
        or immediate_integrity_failure
    )
    updated = False
    if should_update:
        next_state = update_policy_from_evaluations(state, evaluations)
        last_eval = saved[-1] if saved else str((evaluations[-1] or {}).get("evaluation_id") or "none")
        next_state = save_policy_state_with_ledger(
            next_state,
            expected_version=state.version,
            evaluation_id=last_eval,
            ledger_payload={"from": state.model_dump(mode="json"), "to": next_state.model_dump(mode="json")},
        )
        state = next_state
        updated = True
    return {
        "pending_seen": len(pending),
        "evaluations_saved": saved,
        "policy_updated": updated,
        "policy_state": state.state,
        "applied_weight": state.applied_weight,
        "epoch": state.epoch,
    }
