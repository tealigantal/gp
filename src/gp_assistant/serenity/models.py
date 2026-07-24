from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SerenityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SerenityFact(SerenityModel):
    fact_id: str
    symbol: str
    fact_type: str
    claim: str
    occurred_at: str | None = None
    published_at: str | None = None
    effective_available_at: str
    source_document_id: str
    source_version_id: str
    source: str
    source_url: str
    content_sha256: str
    direction: int = 0
    confidence: float = 0.0
    source_quality: float = 0.0
    verification_state: str = "unverified"
    evidence_excerpt: str = ""
    numeric_values: dict[str, Any] = Field(default_factory=dict)
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
    horizon_days: list[int] = Field(default_factory=lambda: [1, 3, 5])
    expected_observation: str = ""
    falsifiers: list[str] = Field(default_factory=list)
    direction: int = 0
    confidence: float = 0.0
    source_quality: float = 0.0
    effective_available_at: str
    evidence_refs: list[str] = Field(default_factory=list)
    status: str = "unverified"

    @field_validator("direction")
    @classmethod
    def _direction(cls, value: int) -> int:
        return -1 if int(value) < 0 else 1 if int(value) > 0 else 0
