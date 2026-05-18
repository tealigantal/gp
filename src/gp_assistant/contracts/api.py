from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    message: Dict[str, Any] = Field(default_factory=dict)
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    planner_trace: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    grounding_summary: Dict[str, Any] = Field(default_factory=dict)


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
    publish_allowed: bool = False
    repair_status: str = "idle"
    repair_stage: str = "idle"
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
    artifact_status: Optional[str] = None
    artifact_lag_reason: Optional[str] = None
    artifact_lag_fields: List[str] = Field(default_factory=list)
    daily_checked_count: int = 0
    daily_stale_count: int = 0
    daily_last_reconcile_at: Optional[str] = None
    daily_blocking_reason: Optional[str] = None
    daily_stale_symbols: List[str] = Field(default_factory=list)
    daily_failed_symbols: List[str] = Field(default_factory=list)
    services: List[RuntimeToolInfo] = Field(default_factory=list)


class OpsRunResponse(BaseModel):
    operation: str
    status: str = "ok"
    message: str
    executed_at: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    runtime: RuntimeStatus = Field(default_factory=RuntimeStatus)


class HealthResponse(BaseModel):
    status: str
    trading_day: Optional[str] = None
    book_version: Optional[str] = None
    llm_ready: bool = False
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
