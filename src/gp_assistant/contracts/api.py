from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(min_length=1)
    client_turn_id: str = Field(min_length=1)

    @field_validator("message", "client_turn_id")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("must_not_be_blank")
        return text


class ChatResponse(BaseModel):
    """The single presentation contract for a committed assistant turn.

    The real LLM narration has one authoritative representation: ``reply``.
    ``message.narrative_text`` is a required rendering projection of that same
    text, never a second independently produced answer.  Writers, idempotent
    replays, and Workspace read projections all normalize through this model.
    """

    session_id: str
    client_turn_id: str
    snapshot_id: Optional[str] = None
    decision: str
    reply: str
    message: Dict[str, Any] = Field(default_factory=dict)
    symbols: List[str] = Field(default_factory=list)

    @field_validator("session_id", "client_turn_id", "decision", "reply")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("assistant_turn_required_text_missing")
        return text

    @model_validator(mode="after")
    def _bind_narrative_to_reply(self) -> "ChatResponse":
        message = dict(self.message or {})
        message["message_kind"] = str(message.get("message_kind") or "chat").strip() or "chat"
        # The body shown to the user is exactly the validated provider output.
        # No display-only fallback text is generated here.
        message["narrative_text"] = self.reply
        self.message = message
        return self

    @classmethod
    def project_persisted(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        assistant_content: str,
        session_id: str,
        client_turn_id: str,
    ) -> dict[str, Any]:
        """Project old or new stored turns into the sole renderable contract.

        This is intentionally read/write compatible: legacy rows are repaired
        in the API projection only, while new rows are normalized before they
        are committed.  The function never creates prose; it can only reuse
        the already committed assistant content.
        """

        projected = dict(payload or {})
        reply = str(projected.get("reply") or assistant_content or "").strip()
        raw_message = projected.get("message")
        message = dict(raw_message) if isinstance(raw_message, Mapping) else {}
        raw_symbols = projected.get("symbols")
        symbols = (
            [str(symbol) for symbol in raw_symbols if str(symbol)]
            if isinstance(raw_symbols, (list, tuple, set))
            else []
        )
        projected.update(
            {
                "session_id": str(projected.get("session_id") or session_id),
                "client_turn_id": str(
                    projected.get("client_turn_id") or client_turn_id
                ),
                "decision": str(
                    projected.get("decision")
                    or message.get("message_kind")
                    or "chat"
                ),
                "reply": reply,
                "message": message,
                "symbols": symbols,
            }
        )
        # Keep persistence-only fields (for example the redacted-at-read
        # ``llm_trace``) intact in storage while the FastAPI response model
        # continues to expose only its declared public fields.
        normalized = cls.model_validate(projected)
        projected.update(normalized.model_dump(mode="json"))
        return projected


class ChatHistoryResponse(BaseModel):
    session_id: str
    turns: List[Dict[str, Any]] = Field(default_factory=list)


class HealthStorageStats(BaseModel):
    session_count: int = 0
    transcript_count: int = 0
    claim_count: int = 0
    latest_session_at: Optional[str] = None


class RuntimeToolInfo(BaseModel):
    service: str
    mode: str
    command: str
    description: str
    profile: Optional[str] = None


class SerenityRuntimeStatus(BaseModel):
    mode: str = "off"
    state: str = "off"
    available: bool = False
    bootstrap_ready: bool = False
    bootstrap_run_id: Optional[str] = None
    stale: bool = False
    applied_weight: float = 0.0
    stored_applied_weight: float = 0.0
    policy_state: Optional[str] = None
    max_weight: float = 0.08
    epoch: int = 1
    worker_heartbeat_at: Optional[str] = None
    worker_lease_expires_at: Optional[str] = None
    last_poll_at: Optional[str] = None
    last_complete_poll_at: Optional[str] = None
    next_due_at: Optional[str] = None
    last_elapsed_sec: Optional[float] = None
    ewma_elapsed_sec: float = 0.0
    p90_elapsed_sec: float = 0.0
    last_poll_status: Optional[str] = None
    last_poll_complete: bool = False
    source_health: Dict[str, Any] = Field(default_factory=dict)
    breaker: Dict[str, Any] = Field(default_factory=dict)
    document_count: int = 0
    withdrawn_count: int = 0
    unparsed_count: int = 0
    matured_days: int = 0
    available_results: int = 0
    last_evaluation_at: Optional[str] = None
    suspension_reasons: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class RuntimeStatus(BaseModel):
    market_phase: str = "UNKNOWN"
    calendar_source: Optional[str] = None
    calendar_status: Optional[str] = None
    calendar_range: Optional[Dict[str, Any]] = None
    calendar_error: Optional[str] = None
    next_trading_day: Optional[str] = None
    data_provider: str = "unknown"
    auto_update_service: str = "gp-worker"
    auto_update_expected: bool = False
    intraday_runtime_enabled: bool = False
    worker_poll_interval_sec: int = 15
    book_freshness: str = "unavailable"
    book_updated_at: Optional[str] = None
    artifact_id: Optional[str] = None
    daybook_effective_day: Optional[str] = None
    pulse_trade_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    last_closed_5m: Optional[str] = None
    slot_status: Optional[str] = None
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    publish_allowed: bool = False
    repair_status: str = "idle"
    repair_stage: str = "idle"
    daily_data_state: Optional[str] = None
    daily_status: Optional[str] = None
    daily_freshness_ready: bool = False
    daily_target_day: Optional[str] = None
    daily_target_mode: Optional[str] = None
    pending_eod_day: Optional[str] = None
    eod_probe: Optional[Dict[str, Any]] = None
    pulse_target_trade_day: Optional[str] = None
    pulse_target_slot_at: Optional[str] = None
    last_repair_started_at: Optional[str] = None
    last_repair_finished_at: Optional[str] = None
    blocking_reason: Optional[str] = None
    clock_data_status: Optional[str] = None
    artifact_stage: str = "none"
    artifact_freshness: str = "unavailable"
    artifact_status: Optional[str] = None
    artifact_lag_reason: Optional[str] = None
    artifact_lag_fields: List[str] = Field(default_factory=list)
    tradeability_state: str = "blocked"
    daily_checked_count: int = 0
    daily_stale_count: int = 0
    daily_last_reconcile_at: Optional[str] = None
    daily_blocking_reason: Optional[str] = None
    daily_stale_symbols: List[str] = Field(default_factory=list)
    daily_failed_symbols: List[str] = Field(default_factory=list)
    services: List[RuntimeToolInfo] = Field(default_factory=list)
    serenity: SerenityRuntimeStatus = Field(default_factory=SerenityRuntimeStatus)
    producer: Dict[str, str] = Field(default_factory=dict)
    current_artifact_compatible: bool = False


class OpsRunResponse(BaseModel):
    operation: str
    status: str = "ok"
    message: str
    executed_at: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeStatus = Field(default_factory=RuntimeStatus)


class HealthResponse(BaseModel):
    status: str
    product_ready: bool = False
    readiness_reasons: List[str] = Field(default_factory=list)
    agent_db: Dict[str, Any] = Field(default_factory=dict)
    current_snapshot: Optional[Dict[str, Any]] = None
    history_db: Dict[str, Any] = Field(default_factory=dict)
    llm: Dict[str, Any] = Field(default_factory=dict)
    serenity: Dict[str, Any] = Field(default_factory=dict)
    worker: Dict[str, Any] = Field(default_factory=dict)
    # Workspace read-model fields.  They are derived from the same immutable
    # snapshot as chat rather than from the retired runtime/book stores.
    llm_ready: bool = False
    # A rejected narration must not prevent a user from issuing the next real
    # LLM request.  This reflects configuration only, not a local fallback.
    llm_retryable: bool = False
    storage: HealthStorageStats = Field(default_factory=HealthStorageStats)
    runtime: RuntimeStatus = Field(default_factory=RuntimeStatus)


class SessionResponse(BaseModel):
    session: Dict[str, Any]
    recent_turns: List[Dict[str, Any]] = Field(default_factory=list)
    recent_claims: List[Dict[str, Any]] = Field(default_factory=list)


class BookResponse(BaseModel):
    book: Dict[str, Any]


class RunResponse(BaseModel):
    run: Dict[str, Any]
