from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.objects import AdvicePick, BoardEntry, DayBook, SymbolPulse
from ..intraday.plans import (
    NEXT_SESSION_PLAN,
    NO_TRADE,
    TRADING_SIGNAL,
    TRIGGER_PLAN,
    UNAVAILABLE,
    compact_strategy,
    finite_float,
)


def _summary_for_state(state: str) -> str:
    state = str(state or "").lower()
    if state == "invalidated":
        return "Plan invalidated by stop or structural support."
    if state in {"actionable", "plan_ready", "daily_ready"}:
        return "Daily plan is ready; wait for the plan's execution rules."
    if state in {"wait_pullback", "waiting_pullback", "waiting_trigger"}:
        return "Logic remains valid, but the trigger has not fired."
    if state in {"extended", "risk_high"}:
        return "Price is extended; chasing risk is high."
    if state in {"below_support", "breakdown_risk"}:
        return "Price is near or below key support; plan risk is high."
    return "Daily plan is not executable yet."


def _summary_for_recommendation_state(state: str, strategy: str | None) -> str:
    if state == TRADING_SIGNAL:
        return f"Current executable signal from {strategy or 'champion strategy'}."
    if state == TRIGGER_PLAN:
        return f"No direct signal yet; waiting for the {strategy or 'champion'} trigger plan."
    if state == NEXT_SESSION_PLAN:
        return f"Next trading-window plan from {strategy or 'champion strategy'}."
    if state == NO_TRADE:
        return "No trade: strategy, RR, risk, or market gate does not support a plan."
    if state == UNAVAILABLE:
        return "Unavailable: real data is insufficient for a decision."
    return _summary_for_state(state)


def _daily_state_from_pick(pick: AdvicePick) -> str:
    meta = dict(pick.meta or {})
    state = str(meta.get("execution_state") or "").strip().lower()
    if state:
        return state
    return "actionable" if bool(meta.get("actionable") is True) else "observe_only"


def _stop_from_pick(pick: AdvicePick):
    plan = pick.stop_plan or {}
    return plan.get("price") or plan.get("stop") or plan.get("level") or plan.get("invalidation")


def _take_from_pick(pick: AdvicePick) -> list:
    plan = pick.take_profit_plan or {}
    values = plan.get("targets") or plan.get("levels") or plan.get("take") or plan.get("prices") or []
    if isinstance(values, list):
        return list(values)
    return [values] if values not in {None, ""} else []


def _rr(entry_mid: float | None, stop: float | None, target: float | None) -> float:
    if entry_mid is None or stop is None or target is None:
        return 0.0
    risk = float(entry_mid) - float(stop)
    reward = float(target) - float(entry_mid)
    if risk <= 0.0 or reward <= 0.0:
        return 0.0
    return max(0.0, reward / risk)


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _daily_display_score(raw_score: float) -> float:
    raw = finite_float(raw_score, 0.0)
    if raw < 0.0:
        return max(0.0, min(50.0, 50.0 + raw * 50.0))
    if raw <= 1.0:
        return max(0.0, min(100.0, raw * 100.0))
    return max(0.0, min(100.0, raw))


def _daily_execution_plan_from_pick(pick: AdvicePick) -> Dict[str, Any]:
    entry_zone = dict(pick.entry_plan or {})
    low = entry_zone.get("low") or entry_zone.get("min") or entry_zone.get("price")
    high = entry_zone.get("high") or entry_zone.get("max") or entry_zone.get("price")
    mid = entry_zone.get("mid") or entry_zone.get("entry") or entry_zone.get("price")
    if mid is None and low is not None and high is not None:
        mid = (float(low) + float(high)) / 2.0
    if low is None:
        low = mid
    if high is None:
        high = mid
    stop = _stop_from_pick(pick)
    take = _take_from_pick(pick)
    take1 = take[0] if take else None
    take2 = take[1] if len(take) > 1 else None
    trigger = entry_zone.get("trigger") or entry_zone.get("trigger_price") or high or mid
    rr_entry = trigger or high or mid
    return {
        "trigger_price": trigger,
        "entry_low": low,
        "entry_high": high,
        "entry_mid": mid,
        "rr_entry_price": rr_entry,
        "entry_type": "next_session_daily_plan",
        "stop_price": stop,
        "invalidation_reason": (pick.stop_plan or {}).get("text") or "Daily plan invalidation/stop is breached.",
        "take1": take1,
        "take2": take2,
        "rr_to_take1": _rr(_float_or_none(rr_entry), _float_or_none(stop), _float_or_none(take1)),
        "rr_to_take2": _rr(_float_or_none(rr_entry), _float_or_none(stop), _float_or_none(take2)),
        "signal_valid_until_slot": None,
        "triggered": False,
        "invalidation_rules": ["daily_stop_breached", "daily_setup_freshness_lost"],
        "trigger_conditions": ["next_session_price_reaches_trigger", "intraday_feature_engine_confirms"],
        "confirmation_conditions": ["market_gate_not_blocked", "VWAP/volume/RS confirm after open"],
    }


def _daily_pulse_from_pick(pick: AdvicePick, rank: int, total: int) -> SymbolPulse:
    state = _daily_state_from_pick(pick)
    rank_score = 1.0 if total <= 1 else 1.0 - float((rank - 1) / max(1, total - 1))
    can_open = False
    invalidated = state in {"invalidated", "below_support", "breakdown_risk"}
    extended = state == "extended"
    plan = _daily_execution_plan_from_pick(pick)
    champion_strategy = str(pick.strategy_id or "TREND_CONTINUATION_5M")
    raw_day_score = finite_float(pick.scores.get("final"), 0.0)
    day_score = _daily_display_score(raw_day_score)
    rr_score = min(100.0, max(0.0, finite_float(plan.get("rr_to_take1")) / 2.4 * 100.0))
    live_score = day_score
    score_breakdown = {
        "raw_day_level_alpha_score": raw_day_score,
        "day_level_alpha_score": day_score,
        "champion_strategy_score": day_score,
        "intraday_exec_score": 45.0,
        "live_score": live_score,
        "strategy_score": day_score,
        "execution_quality_score": 45.0,
        "relative_strength_score": 50.0,
        "volume_confirmation_score": 0.0,
        "location_score": 50.0,
        "rr_score": rr_score,
        "risk_penalty": 0.0,
        "data_quality_score": 65.0,
        "market_regime_fit_score": 50.0,
        "score_scale": 100.0,
    }
    risk_pack = {
        "main_risks": list(pick.risk_flags or []),
        "do_not_chase_reason": "This is a next-session plan; wait for intraday trigger confirmation.",
        "what_would_improve": ["intraday_VWAP_RS_volume_confirm_after_open"],
        "what_would_cancel": list(plan.get("invalidation_rules") or []),
        "data_quality_warnings": ["intraday_features_not_available_in_daily_plan"],
        "market_gate_risks": [],
        "late_session_risk": False,
        "stop_too_far_risk": False,
        "rr_not_enough_risk": bool(finite_float(plan.get("rr_to_take1")) < 1.3),
    }
    candidate = {
        "strategy_name": champion_strategy,
        "eligible": bool(plan.get("trigger_price") and plan.get("stop_price")),
        "raw_score": day_score,
        "confidence": min(1.0, day_score / 100.0),
        "expected_edge_score": day_score,
        "execution_quality_score": 45.0,
        "relative_strength_score": 50.0,
        "volume_confirmation_score": 0.0,
        "location_score": 50.0,
        "rr_score": rr_score,
        "regime_fit_score": 50.0,
        "risk_penalty": 0.0,
        "data_quality_penalty": 12.0,
        "reason_codes": [*list((pick.meta or {}).get("reason_codes") or []), "daily_plan"],
        "reject_reasons": [] if plan.get("trigger_price") and plan.get("stop_price") else ["daily_plan_prices_missing"],
        "invalidation_rules": list(plan.get("invalidation_rules") or []),
        "plan": plan,
    }
    recommendation_state = NEXT_SESSION_PLAN if not invalidated else NO_TRADE
    return SymbolPulse(
        symbol=pick.symbol,
        execution_state="next_session_plan" if recommendation_state == NEXT_SESSION_PLAN else state,
        action="WATCH",
        can_open=can_open,
        live_score=live_score,
        daily_rank_score=rank_score,
        exec_score=45.0,
        signal_type="daily_plan",
        entry_zone=dict(pick.entry_plan or {}),
        stop=_stop_from_pick(pick),
        take=_take_from_pick(pick),
        invalidated=invalidated,
        extended=extended,
        reason_codes=[*list((pick.meta or {}).get("reason_codes") or []), "daily_plan"],
        recommendation_state=recommendation_state,
        feature_snapshot={
            "symbol": pick.symbol,
            "slot_status": "DAILY_PLAN",
            "raw_day_level_alpha_score": raw_day_score,
            "data_quality_score": 65.0,
            "bars_complete": False,
            "provider": "daily",
        },
        strategy_candidates=[candidate],
        champion_strategy=champion_strategy,
        champion_strategy_score=day_score,
        execution_plan=plan,
        score_breakdown=score_breakdown,
        strategy_context={
            "champion_strategy": champion_strategy,
            "champion_strategy_score": day_score,
            "strategy_reason_codes": list(candidate.get("reason_codes") or []),
            "strategy_reject_reasons": list(candidate.get("reject_reasons") or []),
            "competing_strategies": [compact_strategy(candidate)],
        },
        risk_pack=risk_pack,
    )


def _context_for_entry(entry: BoardEntry, *, previous_entry: BoardEntry | None, next_entry: BoardEntry | None) -> Dict[str, Any]:
    plan = dict(entry.execution_plan or {})
    strategy_context = dict(entry.strategy_context or {})
    score = dict(entry.score_breakdown or {})
    features = dict(entry.feature_snapshot or {})
    risks = dict(entry.risk_pack or {})
    competing = list(strategy_context.get("competing_strategies") or [])
    if not competing and entry.strategy_candidates:
        competing = [
            compact_strategy(item)
            for item in sorted(entry.strategy_candidates, key=lambda item: finite_float(item.get("raw_score")), reverse=True)[:3]
        ]
    why_ranked = (
        f"rank={entry.rank}, live_score={finite_float(entry.live_score):.2f}, "
        f"champion={entry.champion_strategy or strategy_context.get('champion_strategy') or 'NA'}"
    )
    why_above = None
    if next_entry is not None:
        why_above = (
            f"{entry.symbol} live_score {finite_float(entry.live_score):.2f} vs "
            f"{next_entry.symbol} {finite_float(next_entry.live_score):.2f}; "
            f"strategy {entry.champion_strategy or 'NA'} vs {next_entry.champion_strategy or 'NA'}."
        )
    why_below = None
    if previous_entry is not None:
        why_below = (
            f"{entry.symbol} live_score {finite_float(entry.live_score):.2f} trails "
            f"{previous_entry.symbol} {finite_float(previous_entry.live_score):.2f}; compare execution quality, RR and risk penalty."
        )
    return {
        "symbol": entry.symbol,
        "name": entry.name,
        "rank": entry.rank,
        "recommendation_state": entry.recommendation_state,
        "action": entry.action,
        "can_open": entry.can_open,
        "execution_state": entry.execution_state,
        "artifact_id": entry.artifact_id,
        "slot_id": entry.slot_id,
        "as_of": features.get("slot_at"),
        "target_slot_at": features.get("target_slot_at"),
        "effective_slot_at": features.get("effective_slot_at") or features.get("slot_at"),
        "data_age_sec": features.get("data_age_sec"),
        "freshness_state": features.get("freshness_state"),
        "source_status": features.get("source_status"),
        "runtime_market_phase": features.get("market_phase"),
        "artifact_market_phase": features.get("market_phase"),
        "trigger_price": plan.get("trigger_price"),
        "entry_low": plan.get("entry_low"),
        "entry_high": plan.get("entry_high"),
        "entry_type": plan.get("entry_type"),
        "stop_price": plan.get("stop_price"),
        "invalidation_reason": plan.get("invalidation_reason"),
        "take1": plan.get("take1"),
        "take2": plan.get("take2"),
        "rr_to_take1": plan.get("rr_to_take1"),
        "rr_to_take2": plan.get("rr_to_take2"),
        "signal_valid_until_slot": plan.get("signal_valid_until_slot"),
        "champion_strategy": entry.champion_strategy or strategy_context.get("champion_strategy"),
        "champion_strategy_score": entry.champion_strategy_score or finite_float(strategy_context.get("champion_strategy_score")),
        "strategy_reason_codes": list(strategy_context.get("strategy_reason_codes") or []),
        "strategy_reject_reasons": list(strategy_context.get("strategy_reject_reasons") or []),
        "competing_strategies": competing[:3],
        "day_level_alpha_score": score.get("day_level_alpha_score"),
        "intraday_exec_score": score.get("intraday_exec_score"),
        "live_score": score.get("live_score", entry.live_score),
        "strategy_score": score.get("strategy_score"),
        "execution_quality_score": score.get("execution_quality_score"),
        "relative_strength_score": score.get("relative_strength_score"),
        "volume_confirmation_score": score.get("volume_confirmation_score"),
        "location_score": score.get("location_score"),
        "rr_score": score.get("rr_score"),
        "risk_penalty": score.get("risk_penalty"),
        "data_quality_score": score.get("data_quality_score"),
        "last_price": features.get("last_price") or features.get("close"),
        "vwap": features.get("vwap"),
        "price_vs_vwap": features.get("price_vs_vwap"),
        "ema5": features.get("ema5"),
        "ema13": features.get("ema13"),
        "ema34": features.get("ema34"),
        "trend_stack_score": features.get("trend_stack_score"),
        "atr5m": features.get("atr5m"),
        "realized_vol_recent": features.get("realized_vol_recent"),
        "compression_score": features.get("compression_score"),
        "range_breakout_score": features.get("range_breakout_score"),
        "slot_rel_vol": features.get("slot_rel_vol"),
        "cumulative_volume_run_rate": features.get("cumulative_volume_run_rate"),
        "volume_zscore_by_slot": features.get("volume_zscore_by_slot"),
        "rs_index": features.get("rs_index"),
        "rs_industry": features.get("rs_industry"),
        "rs_candidate_pool": features.get("rs_candidate_pool"),
        "industry_strength_score": features.get("industry_strength_score"),
        "peer_consensus_score": features.get("peer_consensus_score"),
        "distance_to_entry": features.get("distance_to_entry"),
        "distance_to_stop": features.get("distance_to_stop"),
        "distance_to_take1": features.get("distance_to_take1"),
        "extended_flag": features.get("extended_flag"),
        "invalidated_flag": features.get("invalidated_flag"),
        "main_risks": list(risks.get("main_risks") or []),
        "do_not_chase_reason": risks.get("do_not_chase_reason"),
        "what_would_improve": list(risks.get("what_would_improve") or []),
        "what_would_cancel": list(risks.get("what_would_cancel") or []),
        "entry_readiness": plan.get("entry_readiness") or risks.get("entry_readiness"),
        "entry_blockers": list(risks.get("entry_blockers") or (plan.get("entry_readiness") or {}).get("blockers") or []),
        "data_quality_warnings": list(risks.get("data_quality_warnings") or []),
        "market_gate_risks": list(risks.get("market_gate_risks") or []),
        "late_session_risk": risks.get("late_session_risk"),
        "stop_too_far_risk": risks.get("stop_too_far_risk"),
        "rr_not_enough_risk": risks.get("rr_not_enough_risk"),
        "why_ranked_here": why_ranked,
        "why_above_next": why_above,
        "why_below_previous": why_below,
        "rank_change_reason": None,
        "previous_rank": previous_entry.rank if previous_entry else None,
        "current_rank": entry.rank,
        "raw_bar_summary": list(entry.raw_bar_summary or [])[-8:],
        "score_breakdown": score,
        "feature_snapshot": features,
        "risk_pack": risks,
    }


def build_board(
    daybook: DayBook,
    pulse_map: Dict[str, SymbolPulse],
    *,
    artifact_id: str | None = None,
    slot_id: str | None = None,
) -> List[BoardEntry]:
    entries: List[BoardEntry] = []
    total = max(1, len(daybook.picks[:10]))
    for idx, pick in enumerate(daybook.picks[:10], start=1):
        pulse = pulse_map.get(pick.symbol) or _daily_pulse_from_pick(pick, idx, total)
        entries.append(
            BoardEntry(
                symbol=pick.symbol,
                name=pick.name,
                rank=pick.rank,
                final_score=float(pulse.live_score if pulse.live_score else (pick.scores.get("final") or 0.0)),
                live_score=float(pulse.live_score),
                daily_rank_score=float(pulse.daily_rank_score),
                exec_score=float(pulse.exec_score),
                action=pulse.action,
                execution_state=pulse.execution_state,
                can_open=bool(pulse.can_open),
                stretched=bool(pulse.extended),
                extended=bool(pulse.extended),
                invalidated=bool(pulse.invalidated),
                signal_type=pulse.signal_type,
                entry_zone=dict(pulse.entry_zone),
                stop=pulse.stop,
                take=list(pulse.take),
                vwap=pulse.vwap,
                orb30_high=pulse.orb30_high,
                orb30_low=pulse.orb30_low,
                rs_index=pulse.rs_index,
                rs_industry=pulse.rs_industry,
                slot_rel_vol=pulse.slot_rel_vol,
                summary=_summary_for_recommendation_state(pulse.recommendation_state, pulse.champion_strategy),
                reason_codes=list(pulse.reason_codes),
                artifact_id=artifact_id,
                slot_id=slot_id,
                style_label=pick.style_label,
                pick=pick.model_copy(deep=True),
                pulse=pulse,
                recommendation_state=pulse.recommendation_state,
                feature_snapshot=dict(pulse.feature_snapshot or {}),
                raw_bar_summary=list(pulse.raw_bar_summary or []),
                strategy_candidates=list(pulse.strategy_candidates or []),
                champion_strategy=pulse.champion_strategy,
                champion_strategy_score=float(pulse.champion_strategy_score or 0.0),
                execution_plan=dict(pulse.execution_plan or {}),
                score_breakdown=dict(pulse.score_breakdown or {}),
                strategy_context=dict(pulse.strategy_context or {}),
                risk_pack=dict(pulse.risk_pack or {}),
            )
        )
    state_priority = {
        TRADING_SIGNAL: 4,
        TRIGGER_PLAN: 3,
        NEXT_SESSION_PLAN: 2,
        NO_TRADE: 1,
        UNAVAILABLE: 0,
    }
    entries.sort(
        key=lambda entry: (
            state_priority.get(str(entry.recommendation_state or "").upper(), 0),
            1 if entry.can_open else 0,
            0 if entry.invalidated else 1,
            float(entry.live_score or 0.0),
            float(entry.final_score or 0.0),
        ),
        reverse=True,
    )
    for idx, entry in enumerate(entries, start=1):
        entry.rank = idx
        entry.pick.rank = idx
    for idx, entry in enumerate(entries):
        previous_entry = entries[idx - 1] if idx > 0 else None
        next_entry = entries[idx + 1] if idx + 1 < len(entries) else None
        entry.explain_context = _context_for_entry(entry, previous_entry=previous_entry, next_entry=next_entry)
        entry.pick.explain_context = dict(entry.explain_context)
        entry.pick.meta["explain_context"] = dict(entry.explain_context)
        if entry.pulse is not None:
            entry.pulse.explain_context = dict(entry.explain_context)
    return entries
