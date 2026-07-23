from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class ContractModel(BaseModel):
    """Immutable typed data that may cross a persistence or product boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def require_aware_datetime(cls, value: object) -> object:
        if isinstance(value, datetime) and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timezone_aware_datetime_required")
        return value


class InternalModel(BaseModel):
    """Strict typed application-local command or calculation object."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
