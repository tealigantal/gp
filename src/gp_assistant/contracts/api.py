from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    session_id: str
    reply: str
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    planner_trace: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    trading_day: Optional[str] = None
    book_version: Optional[str] = None
    llm_ready: bool = False


class SessionResponse(BaseModel):
    session: Dict[str, Any]
    recent_turns: List[Dict[str, Any]] = Field(default_factory=list)
    recent_claims: List[Dict[str, Any]] = Field(default_factory=list)


class BookResponse(BaseModel):
    book: Dict[str, Any]


class RunResponse(BaseModel):
    run: Dict[str, Any]
