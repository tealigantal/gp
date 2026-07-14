from __future__ import annotations

import math
from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


NATIVE_SERENITY_FORMULA_VERSION = "AdaptiveDecisionEngine.v2+SerenityAlpha.v1"


class SerenityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


VerificationState = Literal["verified", "unverified", "retracted", "superseded"]
SignalStatus = Literal[
    "available",
    "no_relevant_evidence",
    "stale",
    "source_error",
    "not_ready",
    "unparsed",
]
PolicyStage = Literal["warming", "shadow", "probation", "active", "suspended", "off"]


class SerenityFact(SerenityModel):
    fact_id: str
    symbol: str
    fact_type: str
    claim: str
    occurred_at: Optional[str] = None
    published_at: Optional[str] = None
    effective_available_at: str
    source_document_id: str
    source_version_id: str
    source: str
    source_url: str
    content_sha256: str
    direction: int = 0
    confidence: float = 0.0
    source_quality: float = 0.0
    verification_state: VerificationState = "unverified"
    evidence_excerpt: str = ""
    numeric_values: Dict[str, Any] = Field(default_factory=dict)
    backfill_only: bool = False

    @field_validator("direction")
    @classmethod
    def _direction(cls, value: int) -> int:
        return -1 if int(value) < 0 else 1 if int(value) > 0 else 0

    @field_validator("confidence", "source_quality")
    @classmethod
    def _unit_interval(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class SerenityHypothesis(SerenityModel):
    hypothesis_id: str
    fact_id: str
    symbol: str
    event_type: str
    claim: str
    mechanism: str
    horizon_days: List[int] = Field(default_factory=lambda: [1, 3, 5])
    expected_observation: str = ""
    falsifiers: List[str] = Field(default_factory=list)
    direction: int = 0
    confidence: float = 0.0
    source_quality: float = 0.0
    effective_available_at: str
    evidence_refs: List[str] = Field(default_factory=list)
    status: VerificationState = "unverified"

    @field_validator("direction")
    @classmethod
    def _direction(cls, value: int) -> int:
        return -1 if int(value) < 0 else 1 if int(value) > 0 else 0


class FrozenSerenitySignal(SerenityModel):
    schema_version: str = Field(default="SerenityAlphaFeatureSet.v1", validation_alias=AliasChoices("schema_version", "schema"))
    symbol: str
    status: SignalStatus = "not_ready"
    availability: int = 0
    learning_eligible: bool = False
    direction: int = 0
    confidence: float = 0.0
    source_quality: float = 0.0
    alpha_value: float = 0.0
    decision_at: str
    generated_at: str
    target_id: Optional[str] = None
    source_run_id: Optional[str] = None
    evidence_count: int = 0
    fact_ids: List[str] = Field(default_factory=list)
    hypothesis_ids: List[str] = Field(default_factory=list)
    facts: List[SerenityFact] = Field(default_factory=list)
    lineage: Dict[str, Any] = Field(default_factory=dict)
    input_hash: str
    limitations: List[str] = Field(default_factory=list)

    @field_validator("alpha_value")
    @classmethod
    def _signed_unit_interval(cls, value: float) -> float:
        return max(-1.0, min(1.0, float(value)))


class SerenityCandidateTarget(SerenityModel):
    schema_version: str = "SerenityCandidateTarget.v1"
    target_id: str
    decision_trade_day: str
    daybook_effective_day: str
    observed_at: str
    symbols: List[str] = Field(default_factory=list)
    input_hash: str
    created_at: str
    activated_at: Optional[str] = None
    activation_observed_at: Optional[str] = None
    activation_revision: Optional[str] = None


class SerenityPolicyState(SerenityModel):
    schema_version: str = Field(default="SerenityPolicyState.v1", validation_alias=AliasChoices("schema_version", "schema"))
    version: int = 1
    epoch: int = 1
    state: PolicyStage = "warming"
    applied_weight: float = 0.0
    previous_weight: float = 0.0
    max_weight: float = 0.08
    state_since: str
    last_matured_day: Optional[str] = None
    last_evaluation_at: Optional[str] = None
    bootstrap_run_id: Optional[str] = None
    matured_days: int = 0
    available_results: int = 0
    decision_snapshots: int = 0
    supportive_count: int = 0
    conflicting_count: int = 0
    consecutive_passes: int = 0
    consecutive_failures: int = 0
    probation_matured_days: int = 0
    probation_available_results: int = 0
    suspension_reasons: List[str] = Field(default_factory=list)
    cooldown_until: Optional[str] = None
    rolling_metrics: Dict[str, Any] = Field(default_factory=dict)
    source_health: Dict[str, Any] = Field(default_factory=dict)
    transition_log_hash: str = ""
    updated_at: str

    @field_validator("applied_weight", "previous_weight", "max_weight")
    @classmethod
    def _weight(cls, value: float) -> float:
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0.0 or parsed > 0.08:
            raise ValueError("serenity_weight_non_finite_or_out_of_bounds")
        return round(parsed, 2)


class SerenityCounterfactualArm(SerenityModel):
    weight: float
    ranked_symbols: List[str] = Field(default_factory=list)
    selected_symbols: List[str] = Field(default_factory=list)
    scores: Dict[str, float] = Field(default_factory=dict)
    checksum: str


class SerenityReferenceSnapshot(SerenityModel):
    schema_version: str = Field(default="SerenityReferenceSnapshot.v2", validation_alias=AliasChoices("schema_version", "schema"))
    snapshot_id: str
    decision_context_snapshot_id: Optional[str] = None
    decision_day: str
    decision_at: str
    actual_weight: float = 0.0
    policy_state: PolicyStage = "shadow"
    target_symbols: List[str] = Field(default_factory=list)
    signals: Dict[str, FrozenSerenitySignal] = Field(default_factory=dict)
    risk_plans: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    counterfactual_arms: List[SerenityCounterfactualArm] = Field(default_factory=list)
    reference_counterfactual_arms: List[SerenityCounterfactualArm] = Field(default_factory=list)
    baseline_selected_symbols: List[str] = Field(default_factory=list)
    applied_selected_symbols: List[str] = Field(default_factory=list)
    would_change_topk: bool = False
    input_checksum: str
    learning_sample_id: str = ""
    created_at: str
