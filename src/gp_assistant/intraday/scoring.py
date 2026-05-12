from __future__ import annotations

from typing import Any, Dict, List

from .plans import (
    NEXT_SESSION_PLAN,
    NO_TRADE,
    TRADING_SIGNAL,
    TRIGGER_PLAN,
    UNAVAILABLE,
    finite_float,
    is_continuous_intraday,
    is_non_execution_phase,
    plan_has_prices,
)
from .strategies import StrategyCandidate


MAX_ALLOWED_STOP_DISTANCE = 0.045
MIN_DATA_QUALITY_SCORE = 35.0
MIN_TRADING_RR = 1.3


def _candidate_component(candidate: StrategyCandidate, name: str) -> float:
    return finite_float(getattr(candidate, name, 0.0))


def build_score_breakdown(features: Dict[str, Any], champion: StrategyCandidate) -> Dict[str, float]:
    day_level_alpha_score = finite_float(features.get("day_level_alpha_score"))
    champion_strategy_score = finite_float(champion.raw_score)
    execution_quality_score = _candidate_component(champion, "execution_quality_score")
    rr_score = _candidate_component(champion, "rr_score")
    market_regime_fit_score = _candidate_component(champion, "regime_fit_score")
    data_quality_score = finite_float(features.get("data_quality_score"), 0.0)
    live_score = (
        0.36 * day_level_alpha_score
        + 0.24 * champion_strategy_score
        + 0.16 * execution_quality_score
        + 0.10 * rr_score
        + 0.08 * market_regime_fit_score
        + 0.06 * data_quality_score
    )
    if bool(features.get("invalidated_flag")):
        live_score = 0.0
    return {
        "day_level_alpha_score": round(day_level_alpha_score, 4),
        "champion_strategy_score": round(champion_strategy_score, 4),
        "intraday_exec_score": round(execution_quality_score, 4),
        "live_score": round(max(0.0, min(100.0, live_score)), 4),
        "strategy_score": round(champion_strategy_score, 4),
        "execution_quality_score": round(execution_quality_score, 4),
        "relative_strength_score": round(_candidate_component(champion, "relative_strength_score"), 4),
        "volume_confirmation_score": round(_candidate_component(champion, "volume_confirmation_score"), 4),
        "location_score": round(_candidate_component(champion, "location_score"), 4),
        "rr_score": round(rr_score, 4),
        "risk_penalty": round(_candidate_component(champion, "risk_penalty"), 4),
        "data_quality_score": round(data_quality_score, 4),
        "data_quality_penalty": round(_candidate_component(champion, "data_quality_penalty"), 4),
        "market_regime_fit_score": round(market_regime_fit_score, 4),
    }


def build_risk_pack(
    *,
    features: Dict[str, Any],
    champion: StrategyCandidate,
    gate: Any | None,
    recommendation_state: str | None = None,
) -> Dict[str, Any]:
    plan = champion.plan or {}
    risks: List[str] = []
    data_warnings = list(features.get("data_quality_warnings") or [])
    gate_state = str(getattr(gate, "state", "") if gate is not None else "").upper()
    gate_reasons = list(getattr(gate, "reasons", []) or []) if gate is not None else []
    if bool(features.get("extended_flag")):
        risks.append("extended_flag")
    if bool(features.get("invalidated_flag")):
        risks.append("invalidated_flag")
    if finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR:
        risks.append("rr_to_take1_below_1_3")
    if _stop_distance_pct(features, plan) > MAX_ALLOWED_STOP_DISTANCE:
        risks.append("stop_distance_too_far")
    if gate_state in {"BLOCKED", "KILLED"}:
        risks.append("market_gate_blocked")
    if gate_state == "UNAVAILABLE":
        risks.append("market_gate_unavailable")
    if bool(features.get("is_late_session")):
        risks.append("late_session_risk")
    if data_warnings:
        risks.extend(data_warnings)
    improve: List[str] = []
    if finite_float(features.get("price_vs_vwap")) <= 0:
        improve.append("price_reclaim_vwap")
    if finite_float(features.get("slot_rel_vol")) < 1.0:
        improve.append("slot_rel_vol_improves")
    if finite_float(features.get("rs_index")) <= 0:
        improve.append("rs_index_turns_positive")
    if finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR:
        improve.append("wait_for_better_entry_or_higher_target")
    cancel = list(plan.get("invalidation_rules") or [])
    if not cancel:
        cancel = list(champion.invalidation_rules or [])
    return {
        "main_risks": list(dict.fromkeys(risks))[:10],
        "do_not_chase_reason": _do_not_chase_reason(features, champion, gate_state, plan),
        "what_would_improve": list(dict.fromkeys(improve))[:8],
        "what_would_cancel": list(dict.fromkeys(cancel))[:8],
        "data_quality_warnings": data_warnings,
        "market_gate_risks": gate_reasons if gate_state in {"BLOCKED", "DEGRADED", "UNAVAILABLE", "KILLED"} else [],
        "late_session_risk": bool(features.get("is_late_session")),
        "stop_too_far_risk": bool(_stop_distance_pct(features, plan) > MAX_ALLOWED_STOP_DISTANCE),
        "rr_not_enough_risk": bool(finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR),
        "recommendation_state": recommendation_state,
    }


def _do_not_chase_reason(features: Dict[str, Any], champion: StrategyCandidate, gate_state: str, plan: Dict[str, Any]) -> str:
    if champion.strategy_name == "NO_TRADE_STRATEGY":
        return "No eligible strategy has passed entry, risk, and RR gates."
    if gate_state in {"BLOCKED", "KILLED", "UNAVAILABLE"}:
        return f"Market gate is {gate_state.lower()}, so the plan cannot be treated as executable."
    if bool(features.get("extended_flag")) and champion.strategy_name != "TREND_CONTINUATION_5M":
        return "Price is extended beyond the plan location and this champion is not an explicit trend-continuation confirmation."
    if finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR:
        return "RR to take1 is below 1.3; wait for a better trigger or entry location."
    if bool(features.get("is_late_session")):
        return "Late first triggers after 14:30 are blocked for new entries."
    return "Do not chase above the trigger/entry zone; wait for the computed trigger and invalidation rules."


def _stop_distance_pct(features: Dict[str, Any], plan: Dict[str, Any]) -> float:
    close = finite_float(features.get("close"))
    stop = finite_float(plan.get("stop_price"))
    if close <= 0 or stop <= 0:
        return 0.0
    return max(0.0, (close - stop) / close)


def determine_recommendation_state(
    *,
    features: Dict[str, Any],
    champion: StrategyCandidate,
    gate: Any | None,
    market_phase: str | None,
    previous_action: str | None = None,
) -> str:
    gate_state = str(getattr(gate, "state", "") if gate is not None else "").upper()
    plan = champion.plan or {}
    data_quality_score = finite_float(features.get("data_quality_score"))
    if data_quality_score < MIN_DATA_QUALITY_SCORE or not bool(features.get("bars_complete")):
        return UNAVAILABLE
    if champion.strategy_name == "NO_TRADE_STRATEGY" or not champion.eligible or not plan_has_prices(plan):
        return NO_TRADE
    if bool(features.get("invalidated_flag")):
        return NO_TRADE

    if not is_continuous_intraday(market_phase) or is_non_execution_phase(market_phase):
        return NEXT_SESSION_PLAN

    triggered = bool(plan.get("triggered"))
    if not triggered:
        return TRIGGER_PLAN

    if gate_state in {"UNAVAILABLE", ""}:
        return TRIGGER_PLAN
    if gate_state in {"BLOCKED", "KILLED"}:
        return TRIGGER_PLAN
    if bool(features.get("is_late_session")) and str(previous_action or "").upper() != "BUY":
        return TRIGGER_PLAN
    if finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR:
        return TRIGGER_PLAN
    if _stop_distance_pct(features, plan) > MAX_ALLOWED_STOP_DISTANCE:
        return TRIGGER_PLAN
    if bool(features.get("extended_flag")) and champion.strategy_name != "TREND_CONTINUATION_5M":
        return TRIGGER_PLAN
    if data_quality_score < 55.0:
        return TRIGGER_PLAN
    return TRADING_SIGNAL


def action_for_state(state: str) -> str:
    return "BUY" if state == TRADING_SIGNAL else "WATCH"


def can_open_for_state(state: str) -> bool:
    return state == TRADING_SIGNAL


def execution_state_for_recommendation(state: str, strategy_name: str) -> str:
    if state == UNAVAILABLE:
        return "unavailable"
    if state == NO_TRADE:
        return "invalidated" if strategy_name != "NO_TRADE_STRATEGY" else "observe"
    if state == NEXT_SESSION_PLAN:
        return "next_session_plan"
    if state == TRIGGER_PLAN:
        return "waiting_trigger"
    if strategy_name in {"VOLATILITY_BREAKOUT", "GAP_HOLD_AND_GO", "RANGE_EXPANSION_AFTER_COMPRESSION"}:
        return "breakout_buy"
    if strategy_name in {"PULLBACK_RECLAIM", "CONTROLLED_MEAN_REVERSION"}:
        return "reclaim_buy"
    if strategy_name == "MORNING_STRENGTH_AFTERNOON_RELAUNCH":
        return "afternoon_relaunch_buy"
    return "breakout_buy"


def signal_type_for_strategy(strategy_name: str) -> str:
    mapping = {
        "TREND_CONTINUATION_5M": "trend_continuation",
        "VOLATILITY_BREAKOUT": "volatility_breakout",
        "PULLBACK_RECLAIM": "pullback_reclaim",
        "MORNING_STRENGTH_AFTERNOON_RELAUNCH": "afternoon_relaunch",
        "HIGH_RELATIVE_VOLUME_MOMENTUM": "relative_volume_momentum",
        "GAP_HOLD_AND_GO": "gap_hold_and_go",
        "RANGE_EXPANSION_AFTER_COMPRESSION": "compression_expansion",
        "RELATIVE_STRENGTH_LEADER": "relative_strength_leader",
        "CONTROLLED_MEAN_REVERSION": "controlled_mean_reversion",
        "NO_TRADE_STRATEGY": "no_trade",
    }
    return mapping.get(strategy_name, "strategy_plan")
