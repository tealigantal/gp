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
from ..core.config import load_config
from ..evidence.daily_freshness import active_freshness_for_current_target
from .dialogue_text import clean_user_reason, clean_user_reasons
from ..runtime.market_clock import (
    PHASE_CLOSING_AUCTION,
    PHASE_INTRADAY_AM,
    PHASE_INTRADAY_PM,
    PHASE_LUNCH_BREAK,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_POSTCLOSE_PENDING,
    PHASE_POSTCLOSE_READY,
    PHASE_PREOPEN,
)


BUY_SIGNAL_STATES = {"breakout_buy", "reclaim_buy", "afternoon_relaunch_buy"}


def _intraday_runtime_enabled() -> bool:
    return bool(getattr(load_config(), "intraday_runtime_enabled", False))


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
    plan = entry.pick.entry_plan or {}
    for key in ("text", "desc", "range"):
        text = _as_text(plan.get(key))
        if text:
            return text
    return _range_text(_entry_zone_from_entry(entry))


def _stop_value(entry: BoardEntry) -> Optional[float]:
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
    plan = entry.pick.stop_plan or {}
    for key in ("text", "desc", "level"):
        text = _as_text(plan.get(key))
        if text:
            return text
    stop = _stop_value(entry)
    return f"{stop:.2f}" if stop is not None else None


def _take_values(entry: BoardEntry) -> List[float]:
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


def _market_phase_live(market_phase: str | None) -> bool:
    return str(market_phase or "").upper() in {
        PHASE_INTRADAY_AM,
        PHASE_INTRADAY_PM,
        PHASE_LUNCH_BREAK,
    }


def _friendly_gate_reasons(gate: SlotGate | None) -> List[str]:
    if gate is None:
        return []
    mapping = {
        "data_quality_incomplete": "盘中执行数据不完整",
        "snapshot_columns_missing": "市场广度字段缺失",
        "gate_unavailable": "盘中闸门暂不可用",
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
    if gate_state in {"DEGRADED", "BLOCKED", "UNAVAILABLE"}:
        conditions.append("至少 2 只候选重新回到买点附近")
    if not bool(book.publish_allowed):
        conditions.append("下一交易窗口再用 5 分钟量价确认")
    if book.data_quality and not book.data_quality.complete:
        conditions.append("最新 5 分钟快照恢复完整")
    return list(dict.fromkeys(conditions))


def _status_reason(book: MarketBook) -> str:
    if _market_phase_non_trading(book.market_phase):
        return "当前不在连续竞价执行时段，以下为下一交易窗口计划。"
    if book.gate.state == "BLOCKED":
        return "市场闸门未放行，当前更适合观察而不是硬追。"
    if book.gate.state == "DEGRADED":
        return "市场环境偏弱，保留计划但降低执行强度。"
    if book.slot_status and str(book.slot_status).upper() != "OK":
        return "最新 5 分钟执行数据降级，计划保留但只给观察级判断。"
    return _as_text(book.daybook.reason) or "当前有可跟踪计划。"


def _pick_execution_state(entry: BoardEntry, book: MarketBook) -> str:
    signal = str((entry.pulse.execution_state if entry.pulse else entry.execution_state) or "").lower()
    gate_state = str(book.gate.state or "").upper()
    non_trading = _market_phase_non_trading(book.market_phase)
    if entry.invalidated or signal == "invalidated":
        return "INVALIDATED"
    if signal in BUY_SIGNAL_STATES:
        if non_trading:
            return "WAIT_NEXT_SESSION"
        if gate_state == "ALLOW" and bool(book.publish_allowed) and bool(entry.can_open):
            return "BUY_NOW"
        if gate_state == "DEGRADED":
            return "RISK_HIGH"
        if gate_state in {"BLOCKED", "KILLED"}:
            return "WATCH_ONLY"
        return "UNAVAILABLE" if str(book.slot_status or "").upper() != "OK" else "WATCH_ONLY"
    if signal == "wait_pullback":
        return "WAIT_PULLBACK" if not non_trading else "WAIT_NEXT_SESSION"
    if signal == "extended":
        return "RISK_HIGH"
    if signal == "unavailable":
        return "WAIT_NEXT_SESSION" if non_trading else "UNAVAILABLE"
    return "WATCH_ONLY" if not non_trading else "WAIT_NEXT_SESSION"


def _pick_action(entry: BoardEntry, execution_state: str) -> str:
    if execution_state in {"BUY_NOW", "WAIT_PULLBACK", "WAIT_NEXT_SESSION"}:
        return "BUY"
    return "WATCH"


def _pick_risk_level(entry: BoardEntry, execution_state: str, book: MarketBook) -> str:
    if execution_state in {"INVALIDATED", "RISK_HIGH"}:
        return "high"
    if str(book.gate.state or "").upper() == "DEGRADED":
        return "medium_high"
    if execution_state in {"WAIT_PULLBACK", "WATCH_ONLY"}:
        return "medium"
    return "medium_low" if execution_state == "BUY_NOW" else "medium"


def build_canonical_pick(entry: BoardEntry, book: MarketBook) -> CanonicalPick:
    execution_state = _pick_execution_state(entry, book)
    action = _pick_action(entry, execution_state)
    zone = _entry_zone_from_entry(entry)
    entry_text = _entry_text(entry)
    stop = _stop_value(entry)
    stop_text = _stop_text(entry)
    take_values = _take_values(entry)
    take_text = _take_text(entry)

    technical_basis: List[str] = []
    if entry.vwap is not None:
        technical_basis.append(f"VWAP {entry.vwap:.2f}")
    if entry.orb30_high is not None and entry.orb30_low is not None:
        technical_basis.append(f"ORB30 {entry.orb30_low:.2f}-{entry.orb30_high:.2f}")
    if entry.slot_rel_vol is not None:
        technical_basis.append(f"相对量能 {entry.slot_rel_vol:.2f}x")
    if entry.rs_index is not None:
        technical_basis.append(f"相对沪深300 {entry.rs_index * 100:.2f}%")
    if entry.rs_industry is not None:
        technical_basis.append(f"相对行业 {entry.rs_industry * 100:.2f}%")

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
    if book.pulse_slot_at:
        data_provenance["pulse_slot_at"] = book.pulse_slot_at
    if book.gate and book.gate.metrics:
        data_provenance["gate_metrics"] = dict(book.gate.metrics)
    if entry.reason_codes:
        data_provenance["reason_codes"] = list(entry.reason_codes)
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
        can_execute_now=execution_state == "BUY_NOW",
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
        entry_distance_pct=(entry.pulse.entry_distance_pct if entry.pulse else None),
    )


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
    degraded = (
        not bool(book.data_quality.complete)
        or gate_state in {"DEGRADED", "UNAVAILABLE"}
        or bool(_market_phase_non_trading(book.market_phase))
    )
    executable_count = sum(1 for pick in canonical_picks_all if pick.execution_state in {"BUY_NOW", "WAIT_PULLBACK", "WAIT_NEXT_SESSION"})
    watch_only_count = sum(1 for pick in canonical_picks_all if pick.execution_state in {"WATCH_ONLY", "UNAVAILABLE"})
    if not has_plan:
        run_action = "NO_TRADE"
    elif stale_daily_picks:
        run_action = "NO_TRADE"
    elif gate_state == "BLOCKED" and executable_count == 0 and watch_only_count == len(canonical_picks_all):
        run_action = "NO_TRADE"
    elif degraded and gate_state != "ALLOW":
        run_action = "DEGRADED"
    else:
        run_action = "RECOMMEND"
    canonical_picks = [] if run_action == "NO_TRADE" else canonical_picks_all

    no_trade_reasons: List[str] = []
    if run_action == "NO_TRADE":
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
        "pulse_slot_at": book.pulse_slot_at,
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
        book_version=book.book_version,
        as_of=book.updated_at,
        trading_day=book.trading_day,
        daybook_effective_day=book.daybook_effective_day or book.daybook.trading_day,
        pulse_trade_day=book.pulse_trade_day,
        pulse_slot_at=book.pulse_slot_at,
        market_phase=book.market_phase,
        slot_status=book.slot_status,
        run_action=run_action,
        tradeable=bool(book.daybook.tradeable),
        publish_allowed=bool(book.publish_allowed),
        non_trading=_market_phase_non_trading(book.market_phase),
        status_reason=_status_reason(book),
        no_trade_reasons=no_trade_reasons,
        recovery_conditions=_recovery_conditions(book),
        themes=list(book.daybook.themes or []),
        picks=canonical_picks,
        gate=book.gate.model_dump(),
        data_quality=book.data_quality.model_dump(),
        data_provenance=data_provenance,
        tool_trace={
            "gate_state": gate_state,
            "gate_reasons": list(book.gate.reasons or []),
            "data_errors": list(book.data_quality.errors or []),
        },
    )


def build_no_trade_view(run: CanonicalRunArtifact, book: MarketBook) -> NoTradeArtifact:
    intraday_enabled = _intraday_runtime_enabled()
    if run.run_action == "NO_TRADE":
        reasons = run.no_trade_reasons
        summary = "今天不硬给票，当前更适合空仓或等待。"
    else:
        reasons = ["当前不是纯空仓，而是观察或等待下一交易窗口。"]
        if run.non_trading:
            reasons.append("现在不在连续竞价时段，计划需要等下一交易窗口确认。")
        elif run.run_action == "DEGRADED":
            reasons.append("市场环境或执行数据偏弱，先降级观察。")
        summary = "当前不建议立刻动手，但计划并未失效。"
    reasons = clean_user_reasons(reasons)
    recovery_conditions = [] if not intraday_enabled else list(run.recovery_conditions or [])
    market_summary = clean_user_reason(book.daybook.reason) or summary
    status_reason = run.status_reason or summary
    if not intraday_enabled and "5 分钟" in status_reason:
        status_reason = "当前只保留日线计划和观察结论，不提供 5 分钟级别的执行判断。"
    return NoTradeArtifact(
        run_action=run.run_action,
        market_summary=market_summary,
        status_reason=status_reason,
        no_trade_reasons=reasons,
        recovery_conditions=recovery_conditions,
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
    )


def build_live_entry_view(run: CanonicalRunArtifact, pick: CanonicalPick) -> LiveEntryDecisionArtifact:
    intraday_enabled = _intraday_runtime_enabled()
    next_action = {
        "BUY_NOW": "按计划分批执行，避免追高超过买入区。",
        "WAIT_PULLBACK": "逻辑仍在，等回踩买入区或 VWAP 再确认。",
        "WAIT_NEXT_SESSION": "保留计划，下一交易窗口再看 5 分钟确认。",
        "WATCH_ONLY": "先观察，不做主动追价。",
        "RISK_HIGH": "结构未坏，但追高或市场风险偏大，避免硬上。",
        "INVALIDATED": "已触发失效条件，这个计划先取消。",
        "UNAVAILABLE": "当前执行数据不完整，只能保留观察判断。",
    }.get(pick.execution_state, "继续观察。")
    summary = {
        "BUY_NOW": "当前 5 分钟结构满足计划内入场。",
        "WAIT_PULLBACK": "逻辑还在，但位置偏高或确认不完整，等回踩。",
        "WAIT_NEXT_SESSION": "现在不能判断立刻成交，保留下一交易窗口计划。",
        "WATCH_ONLY": "当前只适合观察，不建议直接进。",
        "RISK_HIGH": "结构未破坏，但风险收益比不够好。",
        "INVALIDATED": "价格已经跌破失效条件，计划失效。",
        "UNAVAILABLE": "必要的盘中执行数据暂不完整。",
    }.get(pick.execution_state, "继续观察。")
    if not intraday_enabled:
        next_action = "当前不接入 5 分钟执行数据，先按日线计划观察，不做盘中追价。"
        summary = "当前只保留日线计划和观察结论，不提供 5 分钟级别的即时入场判断。"
    return LiveEntryDecisionArtifact(
        symbol=pick.symbol,
        name=pick.name,
        execution_state=pick.execution_state,
        can_execute_now=pick.can_execute_now,
        next_action=next_action,
        summary=summary,
        gate_state=run.gate.get("state") if isinstance(run.gate, dict) else None,
        gate_reasons=list(run.gate.get("reasons") or []) if isinstance(run.gate, dict) else [],
        vwap=pick.vwap,
        orb30_high=pick.orb30_high,
        orb30_low=pick.orb30_low,
        entry_text=pick.entry_text,
        stop_text=pick.stop_text,
        take_text=pick.take_text,
        entry_distance_pct=pick.entry_distance_pct,
        slot_rel_vol=pick.slot_rel_vol,
        rs_index=pick.rs_index,
        rs_industry=pick.rs_industry,
        reason_codes=pick.reason_codes,
        data_provenance=pick.data_provenance,
        source_run_id=run.run_id,
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
    elif pick.execution_state == "BUY_NOW":
        action = "HOLD"
        reason = "计划仍然有效，持有逻辑未被破坏。"
        trigger = "5 分钟结构仍保持有效"
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
            0 if item.execution_state not in {"INVALIDATED", "UNAVAILABLE"} else 1,
            -float(item.final_score or 0.0),
            -float(item.live_score or 0.0),
        ),
    )
    comparison_points: List[str] = []
    if len(ordered) >= 2:
        leader = ordered[0]
        runner = ordered[1]
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
            }
            for pick in ordered
        ],
        comparison_points=comparison_points,
        source_run_id=run.run_id,
        data_provenance=run.data_provenance,
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
