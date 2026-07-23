from __future__ import annotations

from datetime import date, datetime, time

from ..contracts.catalog import PlanTargetState
from ..contracts.market import MarketId, ResolvedPlanTarget, TradingCalendarRef


def resolve_plan_target(*, now: datetime, completed_daily_date: date | None, calendar: TradingCalendarRef, is_open: bool, next_open_session: date, required_daily_evidence_date: date) -> ResolvedPlanTarget:
    local_date = now.date()
    after_close = now.timetz().replace(tzinfo=None) >= time(15, 0)
    if not is_open:
        state = PlanTargetState.READY if completed_daily_date == required_daily_evidence_date else PlanTargetState.PENDING_DAILY_EVIDENCE
        return ResolvedPlanTarget(market=MarketId.CN_A_MAIN, market_session_date=next_open_session, daily_evidence_date=completed_daily_date, state=state, resolved_at=now, calendar=calendar)
    if not after_close:
        state = PlanTargetState.READY if completed_daily_date == required_daily_evidence_date else PlanTargetState.PENDING_DAILY_EVIDENCE
        return ResolvedPlanTarget(market=MarketId.CN_A_MAIN, market_session_date=local_date, daily_evidence_date=completed_daily_date, state=state, resolved_at=now, calendar=calendar)
    if completed_daily_date != required_daily_evidence_date:
        return ResolvedPlanTarget(market=MarketId.CN_A_MAIN, market_session_date=next_open_session, daily_evidence_date=completed_daily_date, state=PlanTargetState.PENDING_DAILY_EVIDENCE, resolved_at=now, calendar=calendar)
    return ResolvedPlanTarget(market=MarketId.CN_A_MAIN, market_session_date=next_open_session, daily_evidence_date=completed_daily_date, state=PlanTargetState.READY, resolved_at=now, calendar=calendar)
