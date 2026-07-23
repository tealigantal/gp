from __future__ import annotations

from datetime import datetime

from .base import ContractModel
from .catalog import ExecutionStatus, PlanStatus
from .decision import CandidateDecision


class PublicationDecision(ContractModel):
    plan_status: PlanStatus
    execution_status: ExecutionStatus
    tradeable_now: bool
    reason_codes: tuple[str, ...]


class PublicationLineage(ContractModel):
    plan_id: str
    runtime_id: str | None
    producer_revision: str
    source_digest: str


class RecommendationPublication(ContractModel):
    publication_id: str
    plan_id: str
    runtime_id: str | None
    published_at: datetime
    decision: PublicationDecision
    candidates: tuple[CandidateDecision, ...]
    lineage: PublicationLineage
