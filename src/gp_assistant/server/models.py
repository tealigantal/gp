# src/gp_assistant/server/models.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatReq(BaseModel):
    session_id: Optional[str] = None
    message: str
    message_id: Optional[str] = None


class ChatResp(BaseModel):
    session_id: Optional[str] = None
    reply: str
    tool_trace: Dict[str, Any] = Field(default_factory=dict)
    assistant_message_id: Optional[str] = None
    # Optional agent fields (backward compatible)
    agent_trace: Optional[List[Dict[str, Any]]] = None
    resolved_symbol: Optional[str] = None
    degraded: Optional[bool] = None
    degrade_reason: Optional[str] = None
    followup_context: Optional[Dict[str, Any]] = None
    # Phase 1 additions (optional)
    run_id: Optional[str] = None
    symbols: Optional[List[str]] = None
    fallback_used: Optional[bool] = None
    summary: Optional[Dict[str, Any]] = None
    # Phase 2: unified UI protocol
    ui_items: Optional[List[Dict[str, Any]]] = None
    right_panel: Optional[Dict[str, Any]] = None
    planner_trace: Optional[Dict[str, Any]] = None


# Focus update
class FocusReq(BaseModel):
    session_id: Optional[str] = None
    focus_symbol: str

class FocusResp(BaseModel):
    ok: bool
    session_id: str
    focus_symbol: str
    state: Dict[str, Any] = Field(default_factory=dict)


class RecommendReq(BaseModel):
    # mode: default|dev|<custom_mode>
    mode: Optional[str] = Field(default=None, description="recommend mode: default|dev|<custom>")

    date: Optional[str] = Field(default=None, description="YYYY-MM-DD; default uses calendar as_of")
    topk: Optional[int] = Field(default=3, ge=1, le=10)
    universe: Optional[str] = Field(default="auto", description="auto|symbols|...")
    symbols: Optional[List[str]] = None
    risk_profile: Optional[str] = Field(default="normal", description="normal|aggressive|conservative")

    # compact | full (default compact)
    detail: Optional[str] = Field(default="compact", description="compact|full")


class RecommendResp(BaseModel):
    """
    Response schema for recommendation.

    Keep core fields explicit and allow unknown to pass through
    for backward/forward compatibility.
    """

    model_config = ConfigDict(extra="allow")

    as_of: Optional[str] = None
    timezone: Optional[str] = None
    env: Optional[Dict[str, Any]] = None
    themes: Optional[List[Dict[str, Any]]] = None
    picks: Optional[List[Dict[str, Any]]] = None
    tradeable: Optional[bool] = None
    message: Optional[str] = None
    execution_checklist: Optional[List[str]] = None
    disclaimer: Optional[str] = None
    debug: Optional[Dict[str, Any]] = None


class HealthResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    llm_ready: bool
    provider: Dict[str, Any] | Any
    time: str


class OHLCVBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float


class OHLCVResp(BaseModel):
    symbol: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    bars: List[OHLCVBar] = Field(default_factory=list)


# --- Sync API (events) ---


class EventOut(BaseModel):
    id: str
    conversation_id: str
    seq: int
    type: str
    actor_id: str | None = None
    created_at: str
    data: Dict[str, Any] = Field(default_factory=dict)


class SyncEventIn(BaseModel):
    id: str
    conversation_id: str
    type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    actor_id: str | None = None
    created_at: str | None = None


class SyncReq(BaseModel):
    device_id: str
    conv_cursors: Dict[str, int] = Field(default_factory=dict)
    outbox_events: List[SyncEventIn] = Field(default_factory=list)


class SyncResp(BaseModel):
    ack: Dict[str, str] = Field(default_factory=dict)
    deltas: Dict[str, List[EventOut]] = Field(default_factory=dict)
    conversations_delta: List[Dict[str, Any]] = Field(default_factory=list)
    user_settings_delta: List[Dict[str, Any]] = Field(default_factory=list)


# --- Phase 2: Compare & Pick Detail (minimal models) ---


class CompareReq(BaseModel):
    run_id: Optional[str] = None
    symbols: List[str]


class CompareResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    artifact_version: Optional[str] = None
    run_id: Optional[str] = None
    symbols: List[str]
    items: List[Dict[str, Any]]
    ranking: List[str]
    winner_symbol: Optional[str] = None
    summary: Optional[str] = None
    degraded: bool = False
    fallback_used: bool = False
    errors: Optional[List[str]] = None


class PickDetailReq(BaseModel):
    run_id: Optional[str] = None
    symbol: str


class PickDetailResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    artifact_version: Optional[str] = None
    run_id: Optional[str] = None
    as_of: Optional[str] = None
    degraded: bool = False
    fallback_used: bool = False
    item: Dict[str, Any] | None = None
    error: Optional[str] = None


class RecommendV2Resp(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact_version: str = "v2"
    run_id: Optional[str] = None
    as_of: Optional[str] = None
    snapshot_id: Optional[str] = None
    market_regime: Optional[str] = None
    degraded: bool = False
    tradeable: bool = False
    reason: Optional[str] = None
    risk_profile: Optional[str] = None
    universe_name: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    items: List[Dict[str, Any]] = Field(default_factory=list)
    fallback_used: bool = False
    errors: Optional[List[str]] = None


# --- Phase 3: Validation read-only API ---


class StrategyValidationResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    strategy: str
    event_stats: Dict[str, Any] = Field(default_factory=dict)
    walk_forward: Dict[str, Any] = Field(default_factory=dict)
    strategy_health: Dict[str, Any] = Field(default_factory=dict)


class PaperfolioResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = True
    picks: List[Dict[str, Any]] = Field(default_factory=list)


class LiveShadowResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    available: bool = False
    dates: List[str] = Field(default_factory=list)
    latest_date: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)


class ValidationSummaryResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    as_of: Optional[str] = None
    parts: Dict[str, Any] = Field(default_factory=dict)


# --- Phase 7: Execution/Portfolio ---


class OrderIntentOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    intent_id: str
    symbol: str
    side: str
    status: str
    priority: float
    sizing_hint: Optional[float] = None
    gating_decision: Dict[str, Any] = Field(default_factory=dict)


class PortfolioResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    as_of: Optional[str] = None
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    pending_intents: List[Dict[str, Any]] = Field(default_factory=list)
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)


class WorkbenchResp(BaseModel):
    model_config = ConfigDict(extra="allow")

    as_of: Optional[str] = None
    recommend: Dict[str, Any] = Field(default_factory=dict)
    validation_summary: Dict[str, Any] = Field(default_factory=dict)
    portfolio: Dict[str, Any] = Field(default_factory=dict)
    intents_preview: List[Dict[str, Any]] = Field(default_factory=list)
    execution_events: List[Dict[str, Any]] = Field(default_factory=list)
    live_shadow_summary: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    source_status: Dict[str, Any] = Field(default_factory=dict)


class OperatorIntentActionReq(BaseModel):
    action: str  # 'admit' | 'reject' | 'cancel'
    run_id: Optional[str] = None
    as_of: Optional[str] = None
    symbol: Optional[str] = None
    intent_id: Optional[str] = None
    operator_note: Optional[str] = None


class OperatorIntentActionResp(BaseModel):
    ok: bool
    error: Optional[str] = None
    intent_id: Optional[str] = None
