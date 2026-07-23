from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from .base import ContractModel, InternalModel
from .catalog import PlanTargetState


class MarketId(StrEnum):
    CN_A_MAIN = "cn_a_main"


class TradingCalendarRef(ContractModel):
    calendar_id: str
    revision: str
    source: str


class MarketSessionRef(ContractModel):
    market: MarketId
    market_session_date: date
    calendar: TradingCalendarRef


class ResolvedPlanTarget(InternalModel):
    market: MarketId
    market_session_date: date
    daily_evidence_date: date | None
    state: PlanTargetState
    resolved_at: datetime
    calendar: TradingCalendarRef
