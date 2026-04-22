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


class HealthStorageStats(BaseModel):
    session_count: int = 0
    transcript_count: int = 0
    claim_count: int = 0
    latest_session_at: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    trading_day: Optional[str] = None
    book_version: Optional[str] = None
    llm_ready: bool = False
    storage: HealthStorageStats = Field(default_factory=HealthStorageStats)


class SessionResponse(BaseModel):
    session: Dict[str, Any]
    recent_turns: List[Dict[str, Any]] = Field(default_factory=list)
    recent_claims: List[Dict[str, Any]] = Field(default_factory=list)


class BookResponse(BaseModel):
    book: Dict[str, Any]


class RunResponse(BaseModel):
    run: Dict[str, Any]
