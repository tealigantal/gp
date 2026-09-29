from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import Field
from .base import ContractModel

EntryScenario = Literal["new_position", "add_position"]


class EntryEvidence(ContractModel):
    source: str
    symbol: str
    cutoff: datetime
    fetched_at: datetime
    digest: str
    price_basis: Literal["unadjusted_cny"]
    last_price: float
    return_since_open: float | None
    return_15m: float
    return_30m: float
    closes_30m: tuple[float, ...]
    highs_30m: tuple[float, ...]
    lows_30m: tuple[float, ...]
    volume_recent_15m_to_prior_15m: float | None
    vwap: float | None
    price_vs_vwap: float | None
    price_vs_vwap_15m_ago: float | None
    benchmark_return_15m: float | None
    benchmark_return_30m: float | None
    relative_return_30m: float | None
    entry_position: Literal["below", "inside", "above", "unrecorded"]
    stop_breached: bool
    trade_constraints: tuple[str, ...]
    limitations: tuple[str, ...]
    request_ms: float


class EntryJudgment(ContractModel):
    action: Literal["consider_entry", "do_not_enter", "wait", "unconfirmed"]
    trend: Literal["strengthening", "weakening", "repairing", "pullback", "sideways", "mixed", "unconfirmed"]
    conclusion: str = Field(min_length=1, max_length=600)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=5)
    evidence_fields: tuple[str, ...] = Field(min_length=1)
    change: str


class EntryAssessment(ContractModel):
    assessment_id: str
    plan_id: str
    symbol: str
    scenario: EntryScenario
    assessed_at: datetime
    completed_at: datetime
    mode: Literal["live", "historical"]
    evidence: EntryEvidence
    judgment: EntryJudgment
    previous_assessment_id: str | None
    total_ms: float
