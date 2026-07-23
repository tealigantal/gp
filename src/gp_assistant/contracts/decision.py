from __future__ import annotations

from datetime import date, datetime

from .base import ContractModel, InternalModel
from .catalog import CandidateDisposition, PlanStatus
from .evidence import (
    CandidateUniverseBinding,
    DailyEvidenceBinding,
    DecisionPolicyBinding,
    ExpertContribution,
    ProbabilityAssessment,
    ProducerIdentity,
    RankingAssessment,
    RiskAssessment,
    SerenityDecisionBinding,
    SignalAssessment,
)
from .market import MarketId


class TradePlan(ContractModel):
    entry_low: float | None
    entry_high: float | None
    stop_price: float | None
    take_profit_prices: tuple[float, ...]
    action: str
    reason_codes: tuple[str, ...]


class CandidateDecision(ContractModel):
    symbol: str
    name: str
    disposition: CandidateDisposition
    adaptive_score: float
    recommendation_strength: str
    signal: SignalAssessment
    probability: ProbabilityAssessment
    risk: RiskAssessment
    ranking: RankingAssessment
    experts: tuple[ExpertContribution, ...]
    trade_plan: TradePlan
    reason_codes: tuple[str, ...]


class PlanDecision(ContractModel):
    status: PlanStatus
    reason_codes: tuple[str, ...]


class PlanLookupKey(ContractModel):
    market: MarketId
    market_session_date: date
    daily_evidence_date: date | None
    candidate_universe_id: str
    candidate_universe_content_digest: str
    decision_policy_revision: str
    adaptive_policy_state_version: str
    producer_revision: str
    producer_source_digest: str
    selection_policy: str
    risk_profile: str

    def canonical_identity(self) -> str:
        return self.model_dump_json()


class RecommendationPlan(ContractModel):
    plan_id: str
    lookup_key: PlanLookupKey
    market: MarketId
    market_session_date: date
    daily_evidence_date: date | None
    generated_at: datetime
    decision: PlanDecision
    candidate_universe: CandidateUniverseBinding
    daily_evidence: DailyEvidenceBinding | None
    decision_policy: DecisionPolicyBinding
    producer: ProducerIdentity
    evaluated_candidates: tuple[CandidateDecision, ...]
    serenity: SerenityDecisionBinding


class SerenityReferenceSnapshot(ContractModel):
    reference_id: str
    content_digest: str
    state: str


class EvidenceWrite(ContractModel):
    evidence_id: str
    category: str
    content_digest: str


class PlanCommitCommand(InternalModel):
    plan: RecommendationPlan
    serenity_reference: SerenityReferenceSnapshot | None
    evidence_writes: tuple[EvidenceWrite, ...]
