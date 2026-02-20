from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChatReq(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResp(BaseModel):
    session_id: Optional[str] = None
    reply: str
    tool_trace: Dict[str, Any] = Field(default_factory=dict)


class RecommendReq(BaseModel):
    date: Optional[str] = None
    topk: Optional[int] = 3
    universe: Optional[str] = "auto"
    symbols: Optional[List[str]] = None
    risk_profile: Optional[str] = "normal"
    # new: compact | full (default compact)
    detail: Optional[str] = "compact"


class RecommendResp(BaseModel):
    """Response schema for recommendation.

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

