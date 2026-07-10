from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class APIError(Exception):
    status_code: int
    message: str
    detail: Optional[Dict[str, Any]] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "detail": self.detail or {},
            }
        }


class GPAssistantError(Exception):
    pass


class LLMPayloadBudgetExceeded(GPAssistantError):
    def __init__(
        self,
        *,
        stage: str,
        actual_bytes: int,
        limit_bytes: int,
        budget_report: Dict[str, Any],
    ):
        self.stage = str(stage or "llm_payload")
        self.actual_bytes = int(actual_bytes)
        self.limit_bytes = int(limit_bytes)
        self.budget_report = dict(budget_report or {})
        super().__init__(
            f"LLM payload budget exceeded at {self.stage}: "
            f"{self.actual_bytes} > {self.limit_bytes} bytes"
        )

    def detail(self) -> Dict[str, Any]:
        return {
            "code": "llm_payload_budget_exceeded",
            "stage": self.stage,
            "actual_bytes": self.actual_bytes,
            "limit_bytes": self.limit_bytes,
            "budget_report": self.budget_report,
        }


class IntentLLMUnavailable(GPAssistantError):
    def __init__(self, reason: str):
        self.reason = str(reason or "unknown")
        super().__init__(f"LLM intent parser unavailable: {self.reason}")


class IntentParseFailed(GPAssistantError):
    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        raw_output: str | None = None,
        attempts: int = 1,
    ):
        self.reason = str(reason or message)
        self.raw_output = raw_output
        self.attempts = int(attempts)
        super().__init__(message)

    def detail(self) -> Dict[str, Any]:
        detail: Dict[str, Any] = {
            "reason": self.reason,
            "attempts": self.attempts,
        }
        if self.raw_output:
            detail["raw_output"] = self.raw_output
        return detail


class DataProviderError(Exception):
    def __init__(self, message: str, *, symbol: Optional[str] = None):
        super().__init__(message)
        self.symbol = symbol


class MissingCredentialsError(GPAssistantError):
    def __init__(self, provider: str, hint: Optional[str] = None):
        msg = f"缺少凭证: {provider}"
        if hint:
            msg = f"{msg}（{hint}）"
        super().__init__(msg)
        self.provider = provider
        self.hint = hint
