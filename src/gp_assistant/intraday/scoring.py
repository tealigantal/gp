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
    maybe_float,
    plan_has_prices,
)
from .strategies import StrategyCandidate


MAX_ALLOWED_STOP_DISTANCE = 0.045
MIN_DATA_QUALITY_SCORE = 35.0
MIN_EXECUTION_DATA_QUALITY_SCORE = 55.0
MIN_TRADING_RR = 1.3
MIN_ENTRY_SLOT_REL_VOL = 1.3
MIN_ENTRY_RS_INDEX = 0.0
MIN_ENTRY_PRICE_VS_VWAP = 0.0


def _rounded(value: Any) -> float | None:
    parsed = maybe_float(value)
    return None if parsed is None else round(float(parsed), 6)


def _entry_check(
    *,
    name: str,
    meaning: str,
    current: Any,
    threshold: str,
    passed: bool,
    blocker: bool = True,
) -> Dict[str, Any]:
    current_value = current if isinstance(current, (str, bool)) else _rounded(current)
    return {
        "name": name,
        "meaning": meaning,
        "current": current_value,
        "threshold": threshold,
        "passed": bool(passed),
        "blocker": bool(blocker),
    }


def build_entry_readiness(
    *,
    features: Dict[str, Any],
    plan: Dict[str, Any],
    gate: Any | None,
    market_phase: str | None,
    previous_action: str | None = None,
) -> Dict[str, Any]:
    """Unified execution gate for turning a triggered plan into a BUY signal."""
    gate_state = str(getattr(gate, "state", "") if gate is not None else "").upper()
    close = maybe_float(features.get("close") or features.get("last_price"))
    trigger = maybe_float(plan.get("trigger_price"))
    entry_low = maybe_float(plan.get("entry_low"))
    entry_high = maybe_float(plan.get("entry_high"))
    vwap = maybe_float(features.get("vwap"))
    price_vs_vwap = maybe_float(features.get("price_vs_vwap"))
    slot_rel_vol = maybe_float(features.get("slot_rel_vol"))
    rs_index = maybe_float(features.get("rs_index"))
    rs_industry = maybe_float(features.get("rs_industry"))
    industry_strength = maybe_float(features.get("industry_strength_score"))
    rr_to_take1 = maybe_float(plan.get("rr_to_take1"))
    data_quality_score = maybe_float(features.get("data_quality_score"))
    stop_distance = _stop_distance_pct(features, plan)
    continuous = is_continuous_intraday(market_phase) and not is_non_execution_phase(market_phase)
    price_in_plan = bool(
        plan.get("triggered")
        and close is not None
        and trigger is not None
        and entry_low is not None
        and entry_high is not None
        and close >= trigger
        and entry_low <= close <= max(entry_high, trigger * 1.012)
    )
    rs_industry_supported = bool(
        rs_industry is not None
        and (
            rs_industry >= 0
            or (industry_strength is not None and industry_strength >= 55.0)
        )
    )
    checks = [
        _entry_check(
            name="market_phase",
            meaning="Only continuous auction sessions can produce a same-session entry.",
            current=str(market_phase or ""),
            threshold="INTRADAY_AM or INTRADAY_PM",
            passed=continuous,
        ),
        _entry_check(
            name="price_location",
            meaning="Price must have triggered the plan without chasing beyond the entry zone.",
            current=close,
            threshold=f"close >= trigger_price {trigger}; entry zone {entry_low}-{entry_high}",
            passed=price_in_plan,
        ),
        _entry_check(
            name="price_vs_vwap",
            meaning="Price must be above VWAP, so the entry is not below the intraday volume-weighted cost line.",
            current=price_vs_vwap,
            threshold=f"> {MIN_ENTRY_PRICE_VS_VWAP}",
            passed=bool(vwap is not None and vwap > 0 and price_vs_vwap is not None and price_vs_vwap > MIN_ENTRY_PRICE_VS_VWAP),
        ),
        _entry_check(
            name="slot_rel_vol",
            meaning="Current 5-minute volume must be elevated versus the same time-window baseline.",
            current=slot_rel_vol,
            threshold=f">= {MIN_ENTRY_SLOT_REL_VOL}",
            passed=bool(slot_rel_vol is not None and slot_rel_vol >= MIN_ENTRY_SLOT_REL_VOL),
        ),
        _entry_check(
            name="rs_index",
            meaning="Stock must outperform the benchmark index during the current window.",
            current=rs_index,
            threshold=f"> {MIN_ENTRY_RS_INDEX}",
            passed=bool(rs_index is not None and rs_index > MIN_ENTRY_RS_INDEX),
        ),
        _entry_check(
            name="rs_industry",
            meaning="Stock must not be weaker than its industry context.",
            current=rs_industry,
            threshold="rs_industry >= 0 or industry_strength_score >= 55",
            passed=rs_industry_supported,
        ),
        _entry_check(
            name="rr_to_take1",
            meaning="Reward-to-risk to first target must justify the entry.",
            current=rr_to_take1,
            threshold=f">= {MIN_TRADING_RR}",
            passed=bool(rr_to_take1 is not None and rr_to_take1 >= MIN_TRADING_RR),
        ),
        _entry_check(
            name="stop_distance",
            meaning="Stop distance must be controlled enough for a fresh entry.",
            current=stop_distance,
            threshold=f"<= {MAX_ALLOWED_STOP_DISTANCE}",
            passed=stop_distance <= MAX_ALLOWED_STOP_DISTANCE,
        ),
        _entry_check(
            name="market_gate",
            meaning="Market gate must allow new long entries.",
            current=gate_state,
            threshold="ALLOW or DEGRADED, not BLOCKED/KILLED/UNAVAILABLE",
            passed=gate_state not in {"", "UNAVAILABLE", "BLOCKED", "KILLED"},
        ),
        _entry_check(
            name="data_quality",
            meaning="Intraday data must be complete enough to trust the entry decision.",
            current=data_quality_score,
            threshold=f">= {MIN_EXECUTION_DATA_QUALITY_SCORE}",
            passed=bool(data_quality_score is not None and data_quality_score >= MIN_EXECUTION_DATA_QUALITY_SCORE),
        ),
        _entry_check(
            name="late_session",
            meaning="New first entries are blocked late in the session.",
            current=bool(features.get("is_late_session")),
            threshold="False unless previous action is BUY",
            passed=not bool(features.get("is_late_session")) or str(previous_action or "").upper() == "BUY",
        ),
    ]
    blockers = [check["name"] for check in checks if check["blocker"] and not check["passed"]]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
    }


def _candidate_component(candidate: StrategyCandidate, name: str) -> float:
    return finite_float(getattr(candidate, name, 0.0))


def _range_score(value: Any, low: float, high: float, *, default: float = 50.0) -> float:
    parsed = maybe_float(value)
    if parsed is None or high <= low:
        return default
    return max(0.0, min(100.0, 100.0 * (float(parsed) - low) / (high - low)))


def _timing_quality_score(features: Dict[str, Any]) -> float:
    if bool(features.get("no_new_entry_window")):
        return 25.0
    score = 55.0
    if bool(features.get("is_first_30m")):
        score += 8.0
    if bool(features.get("is_lunch_reopen_window")):
        score += 10.0
        if finite_float(features.get("morning_rs_index")) > 0:
            score += 8.0
        close = maybe_float(features.get("close"))
        afternoon_high = maybe_float(features.get("afternoon_open_range_high"))
        if close is not None and afternoon_high is not None and close >= afternoon_high:
            score += 10.0
    if bool(features.get("is_late_session")):
        score -= 18.0
    return max(0.0, min(100.0, score))


def build_score_breakdown(features: Dict[str, Any], champion: StrategyCandidate) -> Dict[str, float]:
    day_level_alpha_score = finite_float(features.get("day_level_alpha_score"))
    champion_strategy_score = finite_float(champion.raw_score)
    execution_quality_score = _candidate_component(champion, "execution_quality_score")
    relative_strength_score = _candidate_component(champion, "relative_strength_score")
    volume_confirmation_score = _candidate_component(champion, "volume_confirmation_score")
    rr_score = _candidate_component(champion, "rr_score")
    market_regime_fit_score = _candidate_component(champion, "regime_fit_score")
    data_quality_score = finite_float(features.get("data_quality_score"), 0.0)
    momentum_score = (
        0.35 * _range_score(features.get("ret_from_open"), -0.02, 0.04)
        + 0.30 * _range_score(features.get("rs_index"), -0.015, 0.025)
        + 0.20 * _range_score(features.get("rs_candidate_pool"), -0.015, 0.025)
        + 0.15 * _range_score(features.get("morning_rs_index"), -0.015, 0.025)
    )
    vwap_alignment_score = (
        0.55 * _range_score(features.get("price_vs_vwap"), -0.006, 0.018)
        + 0.25 * _range_score(features.get("vwap_slope"), -0.002, 0.006)
        + 0.20 * _range_score(features.get("bars_above_vwap_count"), 0.0, 18.0)
    )
    volume_flow_score = (
        0.40 * _range_score(features.get("slot_rel_vol"), 0.6, 1.8)
        + 0.25 * _range_score(features.get("volume_zscore_by_slot"), -1.0, 2.5)
        + 0.20 * _range_score(features.get("volume_expansion_ratio"), 0.7, 2.0)
        + 0.15 * (75.0 if finite_float(features.get("money_flow_proxy")) > 0 else 25.0)
    )
    timing_quality_score = _timing_quality_score(features)
    live_score = (
        0.24 * day_level_alpha_score
        + 0.18 * champion_strategy_score
        + 0.14 * execution_quality_score
        + 0.12 * relative_strength_score
        + 0.10 * volume_flow_score
        + 0.08 * momentum_score
        + 0.06 * vwap_alignment_score
        + 0.04 * rr_score
        + 0.02 * timing_quality_score
        + 0.02 * data_quality_score
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
        "relative_strength_score": round(relative_strength_score, 4),
        "volume_confirmation_score": round(volume_confirmation_score, 4),
        "momentum_score": round(momentum_score, 4),
        "vwap_alignment_score": round(vwap_alignment_score, 4),
        "volume_flow_score": round(volume_flow_score, 4),
        "timing_quality_score": round(timing_quality_score, 4),
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
    entry_readiness = build_entry_readiness(
        features=features,
        plan=plan,
        gate=gate,
        market_phase=str(features.get("market_phase") or ""),
    )
    for blocker in entry_readiness["blockers"]:
        risks.append(f"entry_check_{blocker}_not_met")
    improve: List[str] = []
    if finite_float(features.get("price_vs_vwap")) <= 0:
        improve.append("price_reclaim_vwap")
    if finite_float(features.get("slot_rel_vol")) < MIN_ENTRY_SLOT_REL_VOL:
        improve.append(f"slot_rel_vol_reaches_{MIN_ENTRY_SLOT_REL_VOL}")
    if finite_float(features.get("rs_index")) <= 0:
        improve.append("rs_index_turns_positive")
    if finite_float(plan.get("rr_to_take1")) < MIN_TRADING_RR:
        improve.append("wait_for_better_entry_or_higher_target")
    for blocker in entry_readiness["blockers"]:
        improve.append(f"entry_check_{blocker}_passes")
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
        "entry_readiness": entry_readiness,
        "entry_blockers": list(entry_readiness["blockers"]),
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
    if data_quality_score < MIN_EXECUTION_DATA_QUALITY_SCORE:
        return TRIGGER_PLAN
    entry_readiness = build_entry_readiness(
        features=features,
        plan=plan,
        gate=gate,
        market_phase=market_phase,
        previous_action=previous_action,
    )
    if not bool(entry_readiness.get("ready")):
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
