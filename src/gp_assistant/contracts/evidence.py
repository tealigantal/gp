from __future__ import annotations

from datetime import date

from pydantic import Field

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
    # Historical immutable plans predate these facts. New daily producer
    # always supplies them; None means unrecorded, never an estimated zero.
    expected_return_3d: float | None = None
    estimated_cost: float | None = None
    expected_net_return: float | None = None


class RiskAssessment(ContractModel):
    score: float
    execution_risk: float
    reason_codes: tuple[str, ...]


class RankingAssessment(ContractModel):
    score: float
    rank: int
    reason_codes: tuple[str, ...]
    # None means unrecorded in immutable older plans, never synthetic evidence.
    gain: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    loss: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    support: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    a0: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    n0: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    core_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    policy_revision: str | None = None


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
