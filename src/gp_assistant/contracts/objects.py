from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class GPModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Claim(GPModel):
    claim_id: str
    session_id: str
    subject_type: str
    subject_id: str
    predicate: str
    value: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    turn_id: str
    created_at: str


class TranscriptEvent(GPModel):
    seq: int
    turn_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    meta: Dict[str, Any] = Field(default_factory=dict)


class SessionState(GPModel):
    session_id: str
    created_at: str
    updated_at: str
    active_run_id: Optional[str] = None
    previous_run_id: Optional[str] = None
    focus_subject: Dict[str, Any] = Field(default_factory=dict)
    compare_set: List[str] = Field(default_factory=list)
    user_preferences: Dict[str, Any] = Field(default_factory=dict)
    last_seen_book_version: Optional[str] = None
    last_turn_id: Optional[str] = None
    last_claim_ids: List[str] = Field(default_factory=list)


class TurnFrame(GPModel):
    frame_id: str
    raw_message: str
    subject: str
    request: str
    freshness: str
    references: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    ambiguity: Dict[str, Any] = Field(default_factory=dict)


class AdvicePick(GPModel):
    symbol: str
    name: Optional[str] = None
    rank: int
    strategy_id: Optional[str] = None
    thesis: str = ""
    entry_plan: Dict[str, Any] = Field(default_factory=dict)
    stop_plan: Dict[str, Any] = Field(default_factory=dict)
    take_profit_plan: Dict[str, Any] = Field(default_factory=dict)
    scores: Dict[str, float] = Field(default_factory=dict)
    risk_flags: List[str] = Field(default_factory=list)
    why_selected: str = ""
    why_not_others: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    style_label: Optional[str] = None


class DayBook(GPModel):
    trading_day: str
    generated_at: str
    regime: Dict[str, Any] = Field(default_factory=dict)
    tradeable: bool = False
    reason: Optional[str] = None
    themes: List[str] = Field(default_factory=list)
    picks: List[AdvicePick] = Field(default_factory=list)
    reserve_symbols: List[str] = Field(default_factory=list)
    source_meta: Dict[str, Any] = Field(default_factory=dict)


class SymbolPulse(GPModel):
    symbol: str
    last_bar_at: Optional[str] = None
    pulse_score: float = 0.0
    momentum_state: str = "unknown"
    stretch_state: str = "unknown"
    liquidity_state: str = "unknown"
    execution_state: str = "observe"
    invalidated: bool = False
    entry_distance_pct: Optional[float] = None
    flags: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


class BoardEntry(GPModel):
    symbol: str
    name: Optional[str] = None
    rank: int
    final_score: float
    live_score: float
    execution_state: str
    can_open: bool
    stretched: bool
    invalidated: bool
    summary: str
    style_label: Optional[str] = None
    pick: AdvicePick
    pulse: Optional[SymbolPulse] = None


class SideResult(GPModel):
    event_id: str
    created_at: str
    symbol: Optional[str] = None
    kind: str
    title: str
    body: str
    refs: Dict[str, Any] = Field(default_factory=dict)


class MarketBook(GPModel):
    trading_day: str
    book_version: str
    updated_at: str
    regime: Dict[str, Any] = Field(default_factory=dict)
    daybook: DayBook
    board: List[BoardEntry] = Field(default_factory=list)
    watchset: List[str] = Field(default_factory=list)
    symbol_states: Dict[str, SymbolPulse] = Field(default_factory=dict)
    portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    last_closed_5m: Optional[str] = None
    side_results: List[SideResult] = Field(default_factory=list)


class AdviceRun(GPModel):
    run_id: str
    session_id: str
    book_version: str
    created_at: str
    trading_day: str
    regime: Dict[str, Any] = Field(default_factory=dict)
    tradeable: bool = False
    reason: Optional[str] = None
    picks: List[BoardEntry] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


class EvidencePack(GPModel):
    frame: TurnFrame
    session: SessionState
    book: MarketBook
    active_run: Optional[AdviceRun] = None
    previous_run: Optional[AdviceRun] = None
    subject_entry: Optional[BoardEntry] = None
    compare_entries: List[BoardEntry] = Field(default_factory=list)
    portfolio_slice: Dict[str, Any] = Field(default_factory=dict)
    validation_slice: Dict[str, Any] = Field(default_factory=dict)
    side_results: List[SideResult] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


class Judgment(GPModel):
    kind: str
    summary: str
    run: Optional[AdviceRun] = None
    subject_entry: Optional[BoardEntry] = None
    compare_entries: List[BoardEntry] = Field(default_factory=list)
    exit_view: Dict[str, Any] = Field(default_factory=dict)
    claims: List[Claim] = Field(default_factory=list)
    side_results: List[SideResult] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)


class ReplyBundle(GPModel):
    session_id: str
    text: str
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    planner_trace: Dict[str, Any] = Field(default_factory=dict)
