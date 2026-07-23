from __future__ import annotations

from datetime import date

from .base import ContractModel
from .market import MarketId


class ProducerIdentity(ContractModel):
    name: str
    revision: str
    source_digest: str


class DailyEvidenceBinding(ContractModel):
    market: MarketId
    daily_evidence_date: date
    source: str
    content_digest: str


class CandidateUniverseBinding(ContractModel):
    candidate_universe_id: str
    content_digest: str
    total_count: int
    eligible_count: int
    complete: bool
    source: str


class DecisionPolicyBinding(ContractModel):
    revision: str
    adaptive_policy_state_version: str
    selection_policy: str
    risk_profile: str


class SignalAssessment(ContractModel):
    score: float
    label: str
    reason_codes: tuple[str, ...]


class ProbabilityAssessment(ContractModel):
    probability: float
    confidence: float
    effective_sample_size: float
    uncertainty: float


class RiskAssessment(ContractModel):
    score: float
    execution_risk: float
    reason_codes: tuple[str, ...]


class RankingAssessment(ContractModel):
    score: float
    rank: int
    reason_codes: tuple[str, ...]


class ExpertContribution(ContractModel):
    expert: str
    contribution: float
    weight: float
    reason_codes: tuple[str, ...]


class SerenityDecisionBinding(ContractModel):
    reference_id: str | None
    policy_revision: str
    applied_weight: float
    state: str
    reason_codes: tuple[str, ...]
