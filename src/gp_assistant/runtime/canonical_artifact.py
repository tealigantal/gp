from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..contracts.objects import (
    AdviceRun,
    BoardEntry,
    CanonicalPick,
    CanonicalRunArtifact,
    CompareArtifact,
    ExitDecisionArtifact,
    LiveEntryDecisionArtifact,
    MarketBook,
    NoTradeArtifact,
    PickDetailArtifact,
    RunChangeArtifact,
    SlotGate,
)
from ..intraday.plans import NEXT_SESSION_PLAN, NO_TRADE, TRADING_SIGNAL, TRIGGER_PLAN, UNAVAILABLE, compact_context, finite_float
from ..evidence.daily_freshness import active_freshness_for_current_target
from .dialogue_text import clean_user_reason, clean_user_reasons
from ..runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_POSTCLOSE_READY,
    PHASE_PREOPEN,
)


BUY_SIGNAL_STATES = {"breakout_buy", "reclaim_buy", "afternoon_relaunch_buy", "trend_continuation_buy"}


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _list_floats(values: Any) -> List[float]:
    if not isinstance(values, list):
        return []
    out: List[float] = []
    for value in values:
        parsed = _as_float(value)
        if parsed is not None:
            out.append(parsed)
    return out


def _entry_zone_from_entry(entry: BoardEntry) -> Dict[str, Any]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    if plan:
        return {
            "low": plan.get("entry_low"),
            "high": plan.get("entry_high"),
            "mid": plan.get("entry_mid"),
            "trigger": plan.get("trigger_price"),
            "type": plan.get("entry_type"),
        }
    zone = dict(entry.entry_zone or {})
    if zone:
        return zone
    plan = entry.pick.entry_plan or {}
    return {
        "low": plan.get("low") or plan.get("min") or plan.get("price"),
        "high": plan.get("high") or plan.get("max") or plan.get("price"),
        "mid": plan.get("mid") or plan.get("price") or plan.get("entry"),
    }


def _range_text(zone: Dict[str, Any]) -> Optional[str]:
    low = _as_float(zone.get("low"))
    high = _as_float(zone.get("high"))
    mid = _as_float(zone.get("mid"))
    if low is not None and high is not None:
        if abs(low - high) < 1e-6:
            return f"{low:.2f}"
        return f"{low:.2f} - {high:.2f}"
    if mid is not None:
        return f"{mid:.2f}"
    return None


def _entry_text(entry: BoardEntry) -> Optional[str]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    if plan:
        trigger = _as_float(plan.get("trigger_price"))
        low = _as_float(plan.get("entry_low"))
        high = _as_float(plan.get("entry_high"))
        if trigger is not None and low is not None and high is not None:
            return f"trigger {trigger:.2f}, entry {low:.2f} - {high:.2f}"
    plan = entry.pick.entry_plan or {}
    for key in ("text", "desc", "range"):
        text = _as_text(plan.get(key))
        if text:
            return text
    return _range_text(_entry_zone_from_entry(entry))


def _stop_value(entry: BoardEntry) -> Optional[float]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    stop = _as_float(plan.get("stop_price"))
    if stop is not None:
        return stop
    stop = _as_float(entry.stop)
    if stop is not None:
        return stop
    plan = entry.pick.stop_plan or {}
    for key in ("price", "stop", "level", "invalidation"):
        stop = _as_float(plan.get(key))
        if stop is not None:
            return stop
    return None


def _stop_text(entry: BoardEntry) -> Optional[str]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    stop = _as_float(plan.get("stop_price"))
    reason = _as_text(plan.get("invalidation_reason"))
    if stop is not None:
        return f"{stop:.2f}" + (f" ({reason})" if reason else "")
    plan = entry.pick.stop_plan or {}
    for key in ("text", "desc", "level"):
        text = _as_text(plan.get(key))
        if text:
            return text
    stop = _stop_value(entry)
    return f"{stop:.2f}" if stop is not None else None


def _take_values(entry: BoardEntry) -> List[float]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    planned = [value for value in (_as_float(plan.get("take1")), _as_float(plan.get("take2"))) if value is not None]
    if planned:
        return planned
    if entry.take:
        return _list_floats(entry.take)
    plan = entry.pick.take_profit_plan or {}
    for key in ("targets", "levels", "take", "prices"):
        parsed = _list_floats(plan.get(key))
        if parsed:
            return parsed
    single = _as_float(plan.get("price") or plan.get("target") or plan.get("t1"))
    return [single] if single is not None else []


def _take_text(entry: BoardEntry) -> Optional[str]:
    plan = dict(getattr(entry, "execution_plan", {}) or {})
    planned = [value for value in (_as_float(plan.get("take1")), _as_float(plan.get("take2"))) if value is not None]
    if planned:
        rr1 = _as_float(plan.get("rr_to_take1"))
        rr_text = f", RR {rr1:.2f}" if rr1 is not None else ""
        return " / ".join(f"{value:.2f}" for value in planned) + rr_text
    plan = entry.pick.take_profit_plan or {}
    for key in ("text", "desc"):
        text = _as_text(plan.get(key))
        if text:
            return text
    targets = _take_values(entry)
    if not targets:
        return None
    return " / ".join(f"{value:.2f}" for value in targets)


def _market_phase_non_trading(market_phase: str | None) -> bool:
    return str(market_phase or "").upper() in {
        PHASE_PREOPEN,
        PHASE_OPEN_NO_FIRST_BAR,
        PHASE_CLOSING_AUCTION,
        PHASE_POSTCLOSE_PENDING,
        PHASE_POSTCLOSE_READY,
    }


def _friendly_gate_reasons(gate: SlotGate | None) -> List[str]:
    if gate is None:
        return []
    mapping = {
        "data_quality_incomplete": "日线计划数据不完整",
        "snapshot_columns_missing": "市场广度字段缺失",
        "gate_unavailable": "日线计划暂不可用",
    }
    out: List[str] = []
    for reason in gate.reasons:
        text = mapping.get(str(reason), _as_text(reason))
        if text:
            out.append(text)
    return out


def _recovery_conditions(book: MarketBook) -> List[str]:
    conditions: List[str] = []
    gate_state = str(book.gate.state or "").upper()
    if gate_state in {"BLOCKED", "KILLED"}:
        conditions.append("市场广度回到可交易区间")
    if gate_state in {"DEGRADED", "BLOCKED"}:
        conditions.append("至少 2 只候选重新回到买点附近")
    if not bool(book.publish_allowed):
        conditions.append("日线计划重新满足交易条件")
    if book.data_quality and not book.data_quality.complete:
        conditions.append("日线数据恢复完整")
    return list(dict.fromkeys(conditions))


def _status_reason(book: MarketBook) -> str:
    if book.gate.state == "BLOCKED":
        return "市场闸门未放行，当前不适合硬追。"
    if book.gate.state == "DEGRADED":
        return "市场环境偏弱，降低执行强度。"
    if book.slot_status and str(book.slot_status).upper() != "OK":
        return "日线计划数据未完全就绪。"
    return _as_text(book.daybook.reason) or "当前有日线计划。"


def _pick_execution_state(entry: BoardEntry, book: MarketBook) -> str:
    recommendation_state = str(getattr(entry, "recommendation_state", "") or "").upper()
    if recommendation_state == TRADING_SIGNAL:
        return "PLAN_READY"
    if recommendation_state == TRIGGER_PLAN:
        return "WAIT_PULLBACK"
    if recommendation_state == NEXT_SESSION_PLAN:
        return "WAIT_NEXT_SESSION"
    if recommendation_state == UNAVAILABLE:
        return "UNAVAILABLE"
    if recommendation_state == NO_TRADE:
        return "INVALIDATED" if entry.invalidated else "WATCH_ONLY"
    signal = str((entry.pulse.execution_state if entry.pulse else entry.execution_state) or "").lower()
    gate_state = str(book.gate.state or "").upper()
    if entry.invalidated or signal in {"invalidated", "below_support", "breakdown_risk"}:
        return "INVALIDATED"
    if signal in {"actionable", "plan_ready", "daily_ready", *BUY_SIGNAL_STATES}:
        return "PLAN_READY"
    if signal in {"waiting_pullback", "wait_pullback"}:
        return "WAIT_PULLBACK"
    if signal == "extended":
        return "RISK_HIGH"
    if gate_state in {"BLOCKED", "KILLED"}:
        return "WATCH_ONLY"
    if gate_state == "DEGRADED":
        return "RISK_HIGH"
    return "WATCH_ONLY"


def _pick_action(entry: BoardEntry, execution_state: str) -> str:
    if str(getattr(entry, "recommendation_state", "") or "").upper() == TRADING_SIGNAL:
        return "BUY"
    return "WATCH"


def _pick_risk_level(entry: BoardEntry, execution_state: str, book: MarketBook) -> str:
    recommendation_state = str(getattr(entry, "recommendation_state", "") or "").upper()
    if recommendation_state in {UNAVAILABLE, NO_TRADE}:
        return "high" if entry.invalidated else "medium"
    if recommendation_state == TRADING_SIGNAL:
        return "medium_low"
    if execution_state in {"INVALIDATED", "RISK_HIGH"}:
        return "high"
    if execution_state == "WAIT_PULLBACK":
        return "medium"
    if execution_state == "PLAN_READY":
        return "medium_low"
    return "medium"


def build_canonical_pick(entry: BoardEntry, book: MarketBook) -> CanonicalPick:
    execution_state = _pick_execution_state(entry, book)
    action = _pick_action(entry, execution_state)
    recommendation_state = str(getattr(entry, "recommendation_state", "") or "").upper() or UNAVAILABLE
    zone = _entry_zone_from_entry(entry)
    entry_text = _entry_text(entry)
    stop = _stop_value(entry)
    stop_text = _stop_text(entry)
    take_values = _take_values(entry)
    take_text = _take_text(entry)

    explain_context = dict(getattr(entry, "explain_context", {}) or {})
    score_breakdown = dict(getattr(entry, "score_breakdown", {}) or {})
    feature_snapshot = dict(getattr(entry, "feature_snapshot", {}) or {})
    execution_plan = dict(getattr(entry, "execution_plan", {}) or {})
    risk_pack = dict(getattr(entry, "risk_pack", {}) or {})
    strategy_context = dict(getattr(entry, "strategy_context", {}) or {})
    champion_strategy = getattr(entry, "champion_strategy", None) or strategy_context.get("champion_strategy")
    champion_strategy_score = finite_float(getattr(entry, "champion_strategy_score", 0.0) or strategy_context.get("champion_strategy_score"))
    competing_strategies = list(strategy_context.get("competing_strategies") or [])
    if not competing_strategies:
        competing_strategies = [
            {
                "strategy_name": item.get("strategy_name"),
                "eligible": item.get("eligible"),
                "score": item.get("raw_score"),
                "reason_codes": item.get("reason_codes") or [],
                "reject_reasons": item.get("reject_reasons") or [],
            }
            for item in list(getattr(entry, "strategy_candidates", []) or [])[:3]
            if isinstance(item, dict)
        ]
    technical_basis: List[str] = list(strategy_context.get("strategy_reason_codes") or [])[:6]

    missing_fields: List[str] = []
    if not entry_text:
        missing_fields.append("entry")
    if not stop_text:
        missing_fields.append("stop")
    if not take_text:
        missing_fields.append("take")

    thesis = _as_text(entry.pick.thesis) or _as_text(entry.summary) or "计划仍在，等待更明确的执行信号。"
    why_selected = _as_text(entry.pick.why_selected) or _as_text(entry.summary) or thesis
    invalidation = stop_text
    confidence = max(0.0, min(1.0, float(entry.final_score or 0.0) / 100.0 if entry.final_score > 1 else float(entry.final_score or 0.0)))
    if confidence == 0.0:
        confidence = 0.5 if action == "WATCH" else 0.65

    data_provenance = {
        "artifact_id": book.artifact_id,
        "book_version": book.book_version,
        "provider": book.data_quality.provider,
        "breadth_source": (book.data_quality.provider or "unknown"),
        "market_phase": book.market_phase,
        "slot_status": book.slot_status,
    }
    if book.artifact_id:
        data_provenance["artifact_id"] = book.artifact_id
    if book.gate and book.gate.metrics:
        data_provenance["gate_metrics"] = dict(book.gate.metrics)
    if entry.reason_codes:
        data_provenance["reason_codes"] = list(entry.reason_codes)
    data_provenance["recommendation_state"] = recommendation_state
    if champion_strategy:
        data_provenance["champion_strategy"] = champion_strategy
    pick_meta = dict(entry.pick.meta or {})
    if pick_meta.get("daily_last_date"):
        data_provenance["daily_last_date"] = pick_meta.get("daily_last_date")
    if pick_meta.get("daily_freshness_state"):
        data_provenance["daily_freshness_state"] = pick_meta.get("daily_freshness_state")
    daybook_freshness = active_freshness_for_current_target(
        dict(book.daybook.source_meta.get("daily_freshness") or {}),
        book_day=book.daybook_effective_day or book.daybook.trading_day,
    )
    if daybook_freshness.get("target_day"):
        data_provenance["daily_target_day"] = daybook_freshness.get("target_day")

    return CanonicalPick(
        symbol=entry.symbol,
        code=entry.symbol,
        name=entry.name,
        rank=entry.rank,
        action=action,
        execution_state=execution_state,
        can_execute_now=recommendation_state == TRADING_SIGNAL,
        thesis=thesis,
        why_selected=why_selected,
        entry_zone=zone,
        entry_text=entry_text,
        stop=stop,
        stop_text=stop_text,
        invalidation=invalidation,
        take_profit=take_values,
        take_text=take_text,
        confidence=confidence,
        risk_level=_pick_risk_level(entry, execution_state, book),
        score=float(entry.final_score or 0.0),
        final_score=float(entry.final_score or 0.0),
        live_score=float(entry.live_score or 0.0),
        daily_rank_score=float(entry.daily_rank_score or 0.0),
        exec_score=float(entry.exec_score or 0.0),
        technical_basis=technical_basis,
        reason_codes=list(entry.reason_codes or []),
        missing_fields=missing_fields,
        artifact_id=entry.artifact_id or book.artifact_id,
        slot_id=entry.slot_id or book.slot_id,
        data_provenance=data_provenance,
        vwap=entry.vwap,
        orb30_high=entry.orb30_high,
        orb30_low=entry.orb30_low,
        rs_index=entry.rs_index,
        rs_industry=entry.rs_industry,
        slot_rel_vol=entry.slot_rel_vol,
        entry_distance_pct=finite_float(feature_snapshot.get("distance_to_entry")) if feature_snapshot else None,
        recommendation_state=recommendation_state,
        champion_strategy=champion_strategy,
        champion_strategy_score=champion_strategy_score,
        strategy_reason_codes=list(strategy_context.get("strategy_reason_codes") or []),
        strategy_reject_reasons=list(strategy_context.get("strategy_reject_reasons") or []),
        competing_strategies=competing_strategies[:3],
        score_breakdown={key: finite_float(value) for key, value in score_breakdown.items()},
        feature_snapshot=feature_snapshot,
        raw_bar_summary=list(getattr(entry, "raw_bar_summary", []) or [])[-8:],
        execution_plan=execution_plan,
        risk_pack=risk_pack,
        explain_context=explain_context,
    )


def _aggregate_recommendation_state(picks: List[CanonicalPick], book: MarketBook) -> str:
    if not picks:
        if book.data_quality and not book.data_quality.complete:
            return UNAVAILABLE
        return NO_TRADE
    states = [str(pick.recommendation_state or "").upper() for pick in picks]
    if any(state == TRADING_SIGNAL for state in states):
        return TRADING_SIGNAL
    if any(state == TRIGGER_PLAN for state in states):
        return TRIGGER_PLAN
    if any(state == NEXT_SESSION_PLAN for state in states):
        return NEXT_SESSION_PLAN
    if states and all(state == UNAVAILABLE for state in states):
        return UNAVAILABLE
    return NO_TRADE


def _legacy_run_action(recommendation_state: str, *, degraded: bool) -> str:
    if recommendation_state in {NO_TRADE, UNAVAILABLE}:
        return "NO_TRADE"
    if degraded:
        return "DEGRADED"
    return "RECOMMEND"


def _run_evidence_pack_from_picks(book: MarketBook, picks: List[CanonicalPick]) -> Dict[str, Any]:
    full = [pick.explain_context for pick in picks if pick.explain_context]
    pick_symbols = {pick.symbol for pick in picks}
    ranked_board_full = [
        dict(entry.explain_context)
        for entry in list(book.board or [])
        if getattr(entry, "explain_context", None)
    ]
    rivals: List[Dict[str, Any]] = []
    for entry in list(book.board or []):
        if entry.symbol in pick_symbols:
            continue
        if entry.explain_context:
            rivals.append(compact_context(entry.explain_context))
        if len(rivals) >= 3:
            break
    return {
        "top_picks_full_context": full,
        "ranked_board_full_context": ranked_board_full,
        "nearby_rivals_compact_context": rivals,
        "raw_bar_summary": {pick.symbol: list(pick.raw_bar_summary or [])[-8:] for pick in picks if pick.raw_bar_summary},
        "context_policy": {
            "top_picks": "full explain_context",
            "ranked_board": "full explain_context for every ranked board entry",
            "nearby_rivals": "compact score and strategy fields",
            "bars": "last 6-12 five-minute summary bars only",
        },
        "gate": book.gate.model_dump() if book.gate else {},
        "artifact": {
            "artifact_id": book.artifact_id,
            "slot_id": book.slot_id,
            "as_of": book.updated_at,
            "market_phase": book.market_phase,
            "slot_status": book.slot_status,
        },
    }


def build_canonical_run(*, book: MarketBook, run: AdviceRun, picks: Iterable[BoardEntry]) -> CanonicalRunArtifact:
    canonical_picks_all = [build_canonical_pick(entry, book) for entry in picks]
    gate_state = str(book.gate.state or "").upper()
    has_plan = bool(canonical_picks_all)
    stale_daily_picks = [
        pick.symbol
        for pick in canonical_picks_all
        if str(pick.data_provenance.get("daily_freshness_state") or "").strip().lower() not in {"", "current"}
    ]
    raw_daybook_freshness = dict(book.daybook.source_meta.get("daily_freshness") or {})
    daybook_freshness = active_freshness_for_current_target(
        raw_daybook_freshness,
        book_day=book.daybook_effective_day or book.daybook.trading_day,
    )
    blocked_reason = _as_text(daybook_freshness.get("blocking_reason"))
    degraded = not bool(book.data_quality.complete) or gate_state == "DEGRADED"
    recommendation_state = _aggregate_recommendation_state(canonical_picks_all, book)
    executable_count = sum(1 for pick in canonical_picks_all if pick.recommendation_state in {TRADING_SIGNAL, TRIGGER_PLAN, NEXT_SESSION_PLAN})
    watch_only_count = sum(1 for pick in canonical_picks_all if pick.execution_state == "WATCH_ONLY")
    if recommendation_state in {NO_TRADE, UNAVAILABLE}:
        run_action = "NO_TRADE"
    elif stale_daily_picks:
        run_action = "NO_TRADE"
    elif gate_state == "BLOCKED" and executable_count == 0 and watch_only_count == len(canonical_picks_all):
        run_action = "NO_TRADE"
    else:
        run_action = _legacy_run_action(recommendation_state, degraded=bool(degraded and gate_state != "ALLOW"))
    canonical_picks = [] if run_action == "NO_TRADE" else canonical_picks_all
    decision_evidence_pack = _run_evidence_pack_from_picks(book, canonical_picks)

    no_trade_reasons: List[str] = []
    if run_action == "NO_TRADE":
        if recommendation_state == UNAVAILABLE:
            no_trade_reasons.append("real_intraday_data_unavailable")
        if stale_daily_picks:
            no_trade_reasons.append(f"日线数据未补齐到目标交易日：{', '.join(stale_daily_picks[:6])}")
        freshness_blocking_reason = _as_text(daybook_freshness.get("blocking_reason"))
        raw_target = _as_text(raw_daybook_freshness.get("target_day"))
        active_target = _as_text(daybook_freshness.get("target_day"))
        stale_freshness_reason = bool(raw_target and active_target and raw_target != active_target)
        if freshness_blocking_reason:
            no_trade_reasons.append(freshness_blocking_reason)
        elif book.daybook.reason and not stale_freshness_reason:
            no_trade_reasons.append(book.daybook.reason)
        no_trade_reasons.extend(_friendly_gate_reasons(book.gate))
        if not no_trade_reasons:
            no_trade_reasons.append("当前没有足够清晰的可执行标的。")

    data_provenance = {
        "provider": book.data_quality.provider,
        "breadth_source": (book.data_quality.provider or "unknown"),
        "calendar_source": book.calendar_source,
        "artifact_id": book.artifact_id,
        "book_version": book.book_version,
        "slot_status": book.slot_status,
    }
    if book.gate and book.gate.metrics:
        data_provenance["gate_metrics"] = dict(book.gate.metrics)
    daybook_freshness = active_freshness_for_current_target(
        dict(book.daybook.source_meta.get("daily_freshness") or {}),
        book_day=book.daybook_effective_day or book.daybook.trading_day,
    )
    if daybook_freshness:
        data_provenance["daily_freshness"] = {
            "ready": bool(daybook_freshness.get("ready", False)),
            "target_day": daybook_freshness.get("target_day"),
            "stale_symbols": list(daybook_freshness.get("stale_symbols") or []),
            "failed_symbols": list(daybook_freshness.get("failed_symbols") or []),
        }

    return CanonicalRunArtifact(
        run_id=run.run_id,
        artifact_id=book.artifact_id,
        slot_id=book.slot_id,
        book_version=book.book_version,
        as_of=book.updated_at,
        trading_day=book.trading_day,
        daybook_effective_day=book.daybook_effective_day or book.daybook.trading_day,
        pulse_trade_day=book.pulse_trade_day,
        pulse_slot_at=book.pulse_slot_at,
        market_phase=book.market_phase,
        slot_status=("OK" if bool(book.data_quality.complete) else book.slot_status),
        run_action=run_action,
        recommendation_state=recommendation_state,
        tradeable=bool(book.daybook.tradeable),
        publish_allowed=bool(book.publish_allowed),
        non_trading=_market_phase_non_trading(book.market_phase),
        status_reason=_status_reason(book),
        no_trade_reasons=no_trade_reasons,
        recovery_conditions=_recovery_conditions(book),
        themes=[],
        picks=canonical_picks,
        gate=book.gate.model_dump(),
        data_quality=book.data_quality.model_dump(),
        data_provenance=data_provenance,
        explain_context={
            "recommendation_state": recommendation_state,
            "top_symbols": [pick.symbol for pick in canonical_picks],
            "artifact_id": book.artifact_id,
            "slot_id": book.slot_id,
            "as_of": book.updated_at,
            "market_phase": book.market_phase,
        },
        decision_evidence_pack=decision_evidence_pack,
        tool_trace={
            "gate_state": gate_state,
            "gate_reasons": list(book.gate.reasons or []),
            "data_errors": list(book.data_quality.errors or []),
        },
    )


def build_no_trade_view(run: CanonicalRunArtifact, book: MarketBook) -> NoTradeArtifact:
    if run.recommendation_state == UNAVAILABLE:
        reasons = clean_user_reasons(run.no_trade_reasons or ["real_intraday_data_unavailable"])
        summary = "UNAVAILABLE: real data is insufficient, so no trade plan is forced."
        return NoTradeArtifact(
            run_action=UNAVAILABLE,
            market_summary=summary,
            status_reason=run.status_reason or summary,
            no_trade_reasons=reasons,
            recovery_conditions=list(run.recovery_conditions or []),
            data_provenance=run.data_provenance,
            source_run_id=run.run_id,
        )
    if run.run_action == "NO_TRADE":
        reasons = clean_user_reasons(run.no_trade_reasons)
        summary = "今天不硬给票，当前没有足够清晰的日线计划。"
    else:
        reasons = ["当前不是纯空仓，而是日线计划暂不满足入场条件。"]
        summary = "当前不建议立刻动手，但计划并未失效。"
    market_summary = clean_user_reason(book.daybook.reason) or summary
    return NoTradeArtifact(
        run_action=run.run_action,
        market_summary=market_summary,
        status_reason=run.status_reason or summary,
        no_trade_reasons=reasons,
        recovery_conditions=list(run.recovery_conditions or []),
        data_provenance=run.data_provenance,
        source_run_id=run.run_id,
    )


def build_pick_detail_view(run: CanonicalRunArtifact, pick: CanonicalPick) -> PickDetailArtifact:
    return PickDetailArtifact(
        symbol=pick.symbol,
        name=pick.name,
        rank=pick.rank,
        thesis=pick.thesis,
        why_selected=pick.why_selected,
        entry_text=pick.entry_text,
        stop_text=pick.stop_text,
        take_text=pick.take_text,
        invalidation=pick.invalidation,
        execution_state=pick.execution_state,
        risk_level=pick.risk_level,
        reason_codes=pick.reason_codes,
        data_provenance=pick.data_provenance,
        source_run_id=run.run_id,
        explain_context=pick.explain_context,
    )


def _plan_levels_from_pick(pick: CanonicalPick) -> Dict[str, Optional[float]]:
    plan = dict(pick.execution_plan or {})
    ctx = dict(pick.explain_context or {})
    zone = dict(pick.entry_zone or {})
    return {
        "trigger": _as_float(plan.get("trigger_price") or ctx.get("trigger_price") or zone.get("trigger")),
        "entry_low": _as_float(plan.get("entry_low") or ctx.get("entry_low") or zone.get("low")),
        "entry_high": _as_float(plan.get("entry_high") or ctx.get("entry_high") or zone.get("high")),
        "stop": _as_float(plan.get("stop_price") or ctx.get("stop_price") or pick.stop),
        "take1": _as_float(plan.get("take1") or ctx.get("take1") or (pick.take_profit[0] if pick.take_profit else None)),
        "take2": _as_float(plan.get("take2") or ctx.get("take2") or (pick.take_profit[1] if len(pick.take_profit) > 1 else None)),
    }


def _fmt_price(value: Optional[float]) -> str:
    return f"{value:.2f}" if value is not None else "--"


def _plan_position(price: Optional[float], levels: Dict[str, Optional[float]]) -> Dict[str, Any]:
    low = levels.get("entry_low")
    high = levels.get("entry_high")
    trigger = levels.get("trigger")
    stop = levels.get("stop")
    zone_ratio = None
    if price is not None and low is not None and high is not None and high > low:
        zone_ratio = (price - low) / (high - low)
    return {
        "price": price,
        "entry_low": low,
        "entry_high": high,
        "trigger": trigger,
        "stop": stop,
        "in_entry_zone": bool(price is not None and low is not None and high is not None and low <= price <= high),
        "above_trigger": bool(price is not None and trigger is not None and price >= trigger),
        "below_stop": bool(price is not None and stop is not None and price <= stop),
        "zone_ratio": zone_ratio,
        "distance_to_stop_pct": (
            ((price - stop) / price)
            if price is not None and stop is not None and price > 0
            else None
        ),
    }


def _live_quote_basis_text(quote: Dict[str, Any]) -> str:
    source = str(quote.get("source") or "")
    current = _as_float(quote.get("current_price"))
    high = _as_float(quote.get("day_high"))
    avg = _as_float(quote.get("average_price"))
    latest = _as_text(quote.get("latest_time"))
    if source == "akshare:minute_1m":
        bits = [f"已用分钟数据核验到 {latest or '最新可用分钟'}"]
        if current is not None:
            bits.append(f"最新价 {_fmt_price(current)}")
        if high is not None:
            bits.append(f"当日高点 {_fmt_price(high)}")
        if avg is not None:
            bits.append(f"均价 {_fmt_price(avg)}")
        user_quote = dict(quote.get("user_quote") or {})
        user_price = _as_float(user_quote.get("current_price"))
        if quote.get("user_quote_mismatch") and user_price is not None and current is not None:
            bits.append(f"你给的现价 {_fmt_price(user_price)} 与分钟最新价 {_fmt_price(current)} 有差异")
        return "，".join(bits) + "。"
    if source == "akshare:bid_ask":
        bits = ["已用盘口数据核验"]
        if current is not None:
            bits.append(f"最新价 {_fmt_price(current)}")
        if high is not None:
            bits.append(f"当日高点 {_fmt_price(high)}")
        return "，".join(bits) + "。"
    if source == "user":
        user_quote = dict(quote.get("user_quote") or {})
        user_price = _as_float(user_quote.get("current_price") or quote.get("current_price"))
        user_high = _as_float(user_quote.get("day_high") or quote.get("day_high"))
        bits = ["未完成实时核验，以下仅按你给的价格判断"]
        if user_price is not None:
            bits.append(f"现价 {_fmt_price(user_price)}")
        if user_high is not None:
            bits.append(f"当日高点 {_fmt_price(user_high)}")
        return "，".join(bits) + "。"
    return "当前没有拿到可核验的盘中价格，只能按日线计划做条件判断。"


def _live_entry_decision_text(pick: CanonicalPick, quote: Dict[str, Any], position: Dict[str, Any]) -> tuple[str, str]:
    price = _as_float(position.get("price"))
    low = _as_float(position.get("entry_low"))
    high = _as_float(position.get("entry_high"))
    trigger = _as_float(position.get("trigger"))
    stop = _as_float(position.get("stop"))
    zone_ratio = _as_float(position.get("zone_ratio"))
    basis = _live_quote_basis_text(quote)
    plan = f"计划区间 {_fmt_price(low)} - {_fmt_price(high)}，触发价 {_fmt_price(trigger)}，失效/止损 {_fmt_price(stop)}。"
    if price is None:
        decision = "没有可用现价，不能给即时入场动作；先等价格数据恢复后再判断。"
        return f"{basis}\n{plan}\n结论：{decision}", decision
    if bool(position.get("below_stop")):
        decision = "不入场，现价已经触及或低于失效线，先取消这条计划。"
        return f"{basis}\n{plan}\n结论：{decision}", decision
    if bool(position.get("in_entry_zone")):
        if pick.execution_state == "WAIT_PULLBACK":
            if trigger is not None and price < trigger and zone_ratio is not None and zone_ratio >= 0.55:
                decision = "不是标准低吸点；价格仍在买入区间上半部，且没有突破触发价。稳健等回踩，激进只能轻仓试探并严守止损。"
            elif trigger is not None and price >= trigger:
                decision = "价格已经到触发价附近；若分钟走势能继续站稳并放量，可以小仓试探，否则不要追。"
            else:
                decision = "在计划区间内但仍属于等待回踩；更好的动作是等靠近支撑后企稳，激进只能轻仓试探。"
        elif pick.execution_state == "PLAN_READY":
            decision = "在计划区间内，可以按计划分批试探，但仍要用止损线控制风险。"
        elif pick.execution_state == "WAIT_NEXT_SESSION":
            decision = "盘中价格进入计划区间，但这条仍是下一交易窗口计划；现在只做条件观察，不直接追。"
        else:
            decision = "价格在计划区间内，但当前执行状态没有给出买入信号，先观察。"
    elif high is not None and price > high:
        if trigger is not None and price >= trigger:
            decision = "价格已经高于计划区间上沿，只有放量站稳触发价才考虑小仓；稳健做法是不追高。"
        else:
            decision = "价格高于计划区间上沿，性价比不够，先不追。"
    elif low is not None and price < low:
        decision = "价格低于计划区间下沿，先等重新站回区间并企稳，不提前接。"
    else:
        decision = "价格位置还不能和计划区间完整匹配，先不做主动入场。"
    return f"{basis}\n{plan}\n结论：{decision}", decision


def build_live_entry_view(
    run: CanonicalRunArtifact,
    pick: CanonicalPick,
    quote_snapshot: Dict[str, Any] | None = None,
) -> LiveEntryDecisionArtifact:
    next_action = {
        "PLAN_READY": "价格处在日线计划区间内，按买入区、失效位和仓位规则分批处理。",
        "WAIT_PULLBACK": "逻辑仍在，等价格回到买入区再处理。",
        "WATCH_ONLY": "日线计划暂不入场，不做主动追价。",
        "RISK_HIGH": "结构未完全失效，但位置或风险收益比偏高。",
        "INVALIDATED": "已触发失效条件，这个计划先取消。",
    }.get(pick.execution_state, "日线计划暂不入场。")
    summary = {
        "PLAN_READY": "当前满足日线计划区间。",
        "WAIT_PULLBACK": "逻辑还在，但位置不够合适。",
        "WATCH_ONLY": "当前只保留日线计划，不主动入场。",
        "RISK_HIGH": "当前风险偏高。",
        "INVALIDATED": "计划已经失效。",
    }.get(pick.execution_state, "当前按日线计划处理。")
    quote = dict(quote_snapshot or {})
    levels = _plan_levels_from_pick(pick)
    price = _as_float(quote.get("current_price"))
    position = _plan_position(price, levels)
    if quote:
        summary, next_action = _live_entry_decision_text(pick, quote, position)
    explain_context = {
        **dict(pick.explain_context or {}),
        "recommendation_state": pick.recommendation_state,
        "quote_snapshot": quote,
        "plan_position": position,
    }
    vwap = pick.vwap if pick.vwap is not None else _as_float(quote.get("average_price"))
    return LiveEntryDecisionArtifact(
        symbol=pick.symbol,
        name=pick.name,
        execution_state=pick.execution_state,
        can_execute_now=pick.can_execute_now,
        next_action=next_action,
        summary=summary,
        gate_state=run.gate.get("state") if isinstance(run.gate, dict) else None,
        gate_reasons=list(run.gate.get("reasons") or []) if isinstance(run.gate, dict) else [],
        vwap=vwap,
        entry_text=pick.entry_text,
        stop_text=pick.stop_text,
        take_text=pick.take_text,
        reason_codes=pick.reason_codes,
        data_provenance=pick.data_provenance,
        source_run_id=run.run_id,
        explain_context=explain_context,
        quote_snapshot=quote,
        user_quote=dict(quote.get("user_quote") or {}),
        plan_position=position,
    )


def build_exit_view(run: CanonicalRunArtifact, pick: CanonicalPick) -> ExitDecisionArtifact:
    if pick.execution_state == "INVALIDATED":
        action = "SELL"
        reason = "已触发失效条件，不继续恋战。"
        trigger = "跌破失效位"
        confidence = 0.86
    elif pick.execution_state == "RISK_HIGH":
        action = "REDUCE"
        reason = "结构未坏，但位置偏高，优先考虑减仓而不是追加。"
        trigger = "偏离买点 / 追高风险"
        confidence = 0.7
    elif pick.execution_state == "PLAN_READY":
        action = "HOLD"
        reason = "计划仍然有效，持有逻辑未被破坏。"
        trigger = "日线结构仍保持有效"
        confidence = 0.66
    else:
        action = "WATCH"
        reason = "暂无明确卖出触发，先按照止损止盈条件跟踪。"
        trigger = "等待触发条件"
        confidence = 0.58
    return ExitDecisionArtifact(
        symbol=pick.symbol,
        action=action,
        reason=reason,
        trigger=trigger,
        stop=pick.stop,
        invalidation=pick.invalidation,
        take_profit=pick.take_profit,
        current_state=pick.execution_state,
        confidence=confidence,
        source_run_id=run.run_id,
        data_provenance=pick.data_provenance,
    )


def build_compare_view(run: CanonicalRunArtifact, picks: List[CanonicalPick]) -> CompareArtifact:
    ordered = sorted(
        picks,
        key=lambda item: (
            0 if item.can_execute_now else 1,
            0 if item.execution_state != "INVALIDATED" else 1,
            -float(item.final_score or 0.0),
            -float(item.live_score or 0.0),
        ),
    )
    comparison_points: List[str] = []
    if len(ordered) >= 2:
        leader = ordered[0]
        runner = ordered[1]
        comparison_points.append(
            "score_breakdown: "
            f"live {leader.live_score:.2f}/{runner.live_score:.2f}, "
            f"strategy {leader.champion_strategy_score:.2f}/{runner.champion_strategy_score:.2f}, "
            f"exec {finite_float(leader.score_breakdown.get('execution_quality_score')):.2f}/{finite_float(runner.score_breakdown.get('execution_quality_score')):.2f}, "
            f"RR {finite_float(leader.score_breakdown.get('rr_score')):.2f}/{finite_float(runner.score_breakdown.get('rr_score')):.2f}, "
            f"RS {finite_float(leader.score_breakdown.get('relative_strength_score')):.2f}/{finite_float(runner.score_breakdown.get('relative_strength_score')):.2f}, "
            f"risk_penalty {finite_float(leader.score_breakdown.get('risk_penalty')):.2f}/{finite_float(runner.score_breakdown.get('risk_penalty')):.2f}, "
            f"data_quality {finite_float(leader.score_breakdown.get('data_quality_score')):.2f}/{finite_float(runner.score_breakdown.get('data_quality_score')):.2f}."
        )
        comparison_points.append(f"{leader.symbol} 排在前面，主要因为执行状态 {leader.execution_state} 优于 {runner.execution_state}。")
        if float(leader.final_score or 0.0) != float(runner.final_score or 0.0):
            comparison_points.append(f"综合分 {leader.final_score:.2f} 对比 {runner.final_score:.2f}。")
        if leader.risk_level != runner.risk_level:
            comparison_points.append(f"风险级别上，{leader.symbol} 为 {leader.risk_level}，{runner.symbol} 为 {runner.risk_level}。")
    return CompareArtifact(
        compared_symbols=[pick.symbol for pick in ordered],
        leader_symbol=(ordered[0].symbol if ordered else None),
        ranking=[
            {
                "symbol": pick.symbol,
                "rank": pick.rank,
                "execution_state": pick.execution_state,
                "final_score": pick.final_score,
                "live_score": pick.live_score,
                "risk_level": pick.risk_level,
                "recommendation_state": pick.recommendation_state,
                "champion_strategy": pick.champion_strategy,
                "champion_strategy_score": pick.champion_strategy_score,
                "execution_quality_score": finite_float(pick.score_breakdown.get("execution_quality_score")),
                "rr_score": finite_float(pick.score_breakdown.get("rr_score")),
                "relative_strength_score": finite_float(pick.score_breakdown.get("relative_strength_score")),
                "risk_penalty": finite_float(pick.score_breakdown.get("risk_penalty")),
                "data_quality_score": finite_float(pick.score_breakdown.get("data_quality_score")),
            }
            for pick in ordered
        ],
        comparison_points=comparison_points,
        source_run_id=run.run_id,
        data_provenance=run.data_provenance,
        explain_context={
            "compared_symbols": [pick.symbol for pick in ordered],
            "ranking_context": [pick.explain_context for pick in ordered if pick.explain_context],
        },
    )


def build_run_change_view(current_run: AdviceRun | None, previous_run: AdviceRun | None) -> RunChangeArtifact:
    current_map = {entry.symbol: entry for entry in (current_run.picks if current_run else [])}
    previous_map = {entry.symbol: entry for entry in (previous_run.picks if previous_run else [])}
    current_symbols = set(current_map)
    previous_symbols = set(previous_map)
    rank_changes: List[Dict[str, Any]] = []
    for symbol in sorted(current_symbols & previous_symbols):
        if current_map[symbol].rank != previous_map[symbol].rank:
            rank_changes.append(
                {
                    "symbol": symbol,
                    "from_rank": previous_map[symbol].rank,
                    "to_rank": current_map[symbol].rank,
                }
            )
    return RunChangeArtifact(
        current_run_id=(current_run.run_id if current_run else None),
        previous_run_id=(previous_run.run_id if previous_run else None),
        added=sorted(current_symbols - previous_symbols),
        removed=sorted(previous_symbols - current_symbols),
        rank_changes=rank_changes,
        gating_change={
            "current": {
                "run_action": current_run.run_action if current_run else None,
                "tradeable": current_run.tradeable if current_run else None,
                "publish_allowed": current_run.publish_allowed if current_run else None,
                "reason": current_run.reason if current_run else None,
            },
            "previous": {
                "run_action": previous_run.run_action if previous_run else None,
                "tradeable": previous_run.tradeable if previous_run else None,
                "publish_allowed": previous_run.publish_allowed if previous_run else None,
                "reason": previous_run.reason if previous_run else None,
            },
        },
        data_quality_change={
            "current": current_run.data_quality if current_run else {},
            "previous": previous_run.data_quality if previous_run else {},
        },
    )
