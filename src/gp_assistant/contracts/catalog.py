from __future__ import annotations

from enum import StrEnum


class PlanTargetState(StrEnum):
    READY = "ready"
    PENDING_DAILY_EVIDENCE = "pending_daily_evidence"
    UNAVAILABLE = "unavailable"


class PlanStatus(StrEnum):
    RECOMMEND = "recommend"
    NO_RECOMMEND = "no_recommend"
    UNAVAILABLE = "unavailable"


class CandidateDisposition(StrEnum):
    SELECTED = "selected"
    RESERVE = "reserve"
    REJECTED = "rejected"


class ExecutionStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PENDING = "pending"


class MarketPhase(StrEnum):
    PREOPEN = "preopen"
    MORNING = "morning"
    LUNCH = "lunch"
    AFTERNOON = "afternoon"
    CLOSING_AUCTION = "closing_auction"
    POSTCLOSE = "postclose"
    CLOSED = "closed"


class RuntimeDataState(StrEnum):
    READY = "ready"
    STALE = "stale"
    UNAVAILABLE = "unavailable"
