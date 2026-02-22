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