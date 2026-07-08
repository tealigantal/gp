from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .intents import FreshnessType, RequestType, SubjectType


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
    active_run_daybook_effective_day: Optional[str] = None
    active_run_pulse_trade_day: Optional[str] = None
    active_run_pulse_slot_at: Optional[str] = None
    last_focus_rank: Optional[int] = None
    last_focus_symbol: Optional[str] = None


class TurnFrame(GPModel):
    frame_id: str
    raw_message: str
    subject: SubjectType
    request: RequestType
    freshness: FreshnessType
    references: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    ambiguity: Dict[str, Any] = Field(default_factory=dict)


class AdvicePick(GPModel):
    symbol: str
    name: Optional[str] = None
    rank: int
    strategy_id: Optional[str] = None
    industry: Optional[str] = None
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
    explain_context: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)
    signal: Dict[str, Any] = Field(default_factory=dict)
    probability: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)
    ranking: Dict[str, Any] = Field(default_factory=dict)
    historical_cases: List[Dict[str, Any]] = Field(default_factory=list)
    decision_context_snapshot_id: Optional[str] = None


class DayBook(GPModel):
    trading_day: str
    generated_at: str
    regime: Dict[str, Any] = Field(default_factory=dict)
    tradeable: bool = False
    reason: Optional[str] = None
    themes: List[str] = Field(default_factory=list)
    picks: List[AdvicePick] = Field(default_factory=list)
    reserve_picks: List[AdvicePick] = Field(default_factory=list)
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
    live_score: float = 0.0
    daily_rank_score: float = 0.0
    exec_score: float = 0.0
    action: str = "WATCH"
    can_open: bool = False
    signal_type: str = "observe"
    entry_zone: Dict[str, Any] = Field(default_factory=dict)
    stop: Optional[float] = None
    take: List[float] = Field(default_factory=list)
    vwap: Optional[float] = None
    orb30_high: Optional[float] = None
    orb30_low: Optional[float] = None
    rs_index: Optional[float] = None
    rs_industry: Optional[float] = None
    slot_rel_vol: Optional[float] = None
    extended: bool = False
    reason_codes: List[str] = Field(default_factory=list)
    provider: Optional[str] = None
    volume_baseline: Optional[float] = None
    trade_day: Optional[str] = None
    slot_at: Optional[str] = None
    is_stale: bool = False
    stale_reason: Optional[str] = None
    recommendation_state: str = "UNAVAILABLE"
    feature_snapshot: Dict[str, Any] = Field(default_factory=dict)
    raw_bar_summary: List[Dict[str, Any]] = Field(default_factory=list)
    strategy_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    champion_strategy: Optional[str] = None
    champion_strategy_score: float = 0.0
    execution_plan: Dict[str, Any] = Field(default_factory=dict)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    strategy_context: Dict[str, Any] = Field(default_factory=dict)
    risk_pack: Dict[str, Any] = Field(default_factory=dict)
    explain_context: Dict[str, Any] = Field(default_factory=dict)


class BoardEntry(GPModel):
    symbol: str
    name: Optional[str] = None
    rank: int
    final_score: float
    live_score: float
    daily_rank_score: float = 0.0
    exec_score: float = 0.0
    action: str = "WATCH"
    execution_state: str
    can_open: bool
    stretched: bool
    extended: bool = False
    invalidated: bool
    signal_type: str = "observe"
    entry_zone: Dict[str, Any] = Field(default_factory=dict)
    stop: Optional[float] = None
    take: List[float] = Field(default_factory=list)
    vwap: Optional[float] = None
    orb30_high: Optional[float] = None
    orb30_low: Optional[float] = None
    rs_index: Optional[float] = None
    rs_industry: Optional[float] = None
    slot_rel_vol: Optional[float] = None
    summary: str
    reason_codes: List[str] = Field(default_factory=list)
    artifact_id: Optional[str] = None
    slot_id: Optional[str] = None
    style_label: Optional[str] = None
    pick: AdvicePick
    pulse: Optional[SymbolPulse] = None
    recommendation_state: str = "UNAVAILABLE"
    feature_snapshot: Dict[str, Any] = Field(default_factory=dict)
    raw_bar_summary: List[Dict[str, Any]] = Field(default_factory=list)
    strategy_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    champion_strategy: Optional[str] = None
    champion_strategy_score: float = 0.0
    execution_plan: Dict[str, Any] = Field(default_factory=dict)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    strategy_context: Dict[str, Any] = Field(default_factory=dict)
    risk_pack: Dict[str, Any] = Field(default_factory=dict)
    explain_context: Dict[str, Any] = Field(default_factory=dict)


class SideResult(GPModel):
    event_id: str
    created_at: str
    symbol: Optional[str] = None
    kind: str
    title: str
    body: str
    refs: Dict[str, Any] = Field(default_factory=dict)


class SlotGate(GPModel):
    state: str = "UNAVAILABLE"
    score: float = 0.0
    reasons: List[str] = Field(default_factory=list)
    breadth_score: float = 0.0
    benchmark_score: float = 0.0
    liquidity_score: float = 0.0
    buyable_count: int = 0
    metrics: Dict[str, Any] = Field(default_factory=dict)


class SlotDataQuality(GPModel):
    snapshot_age_sec: Optional[float] = None
    symbols_expected: int = 0
    symbols_received: int = 0
    benchmark_received: bool = False
    provider: Optional[str] = None
    complete: bool = False
    errors: List[str] = Field(default_factory=list)
    target_slot_at: Optional[str] = None
    effective_slot_at: Optional[str] = None
    freshness_state: str = "unknown"
    data_age_sec: Optional[float] = None
    fresh_symbols: List[str] = Field(default_factory=list)
    usable_stale_symbols: List[str] = Field(default_factory=list)
    missing_symbols: List[str] = Field(default_factory=list)
    fetch_elapsed_sec: Optional[float] = None
    cache_hit_rate: Optional[float] = None


class TrackedUniverse(GPModel):
    reco: List[str] = Field(default_factory=list)
    reserve: List[str] = Field(default_factory=list)
    portfolio: List[str] = Field(default_factory=list)
    total: List[str] = Field(default_factory=list)


class LiveSlotArtifact(GPModel):
    artifact_id: str
    slot_id: Optional[str] = None
    trade_day: str
    slot_at: Optional[str] = None
    market_phase: str
    slot_status: str = "UNAVAILABLE"
    publish_allowed: bool = False
    daybook_effective_day: str
    gate: SlotGate = Field(default_factory=SlotGate)
    tracked_universe: TrackedUniverse = Field(default_factory=TrackedUniverse)
    board: List[BoardEntry] = Field(default_factory=list)
    symbol_states: Dict[str, SymbolPulse] = Field(default_factory=dict)
    data_quality: SlotDataQuality = Field(default_factory=SlotDataQuality)
    portfolio_snapshot: Dict[str, Any] = Field(default_factory=dict)
    provider_meta: Dict[str, Any] = Field(default_factory=dict)
    side_results: List[SideResult] = Field(default_factory=list)
    created_at: str
    updated_at: str


class CurrentSlotPointer(GPModel):
    artifact_id: str
    trade_day: str
    slot_id: Optional[str] = None
    slot_at: Optional[str] = None
    updated_at: str


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
    artifact_id: Optional[str] = None
    slot_id: Optional[str] = None
    slot_status: Optional[str] = None
    publish_allowed: bool = False
    daybook_effective_day: Optional[str] = None
    pulse_trade_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    market_phase: Optional[str] = None
    data_status: Optional[str] = None
    calendar_source: Optional[str] = None
    gate: SlotGate = Field(default_factory=SlotGate)
    data_quality: SlotDataQuality = Field(default_factory=SlotDataQuality)
    tracked_universe: TrackedUniverse = Field(default_factory=TrackedUniverse)


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
    artifact_id: Optional[str] = None
    slot_id: Optional[str] = None
    slot_status: Optional[str] = None
    publish_allowed: bool = False
    daybook_effective_day: Optional[str] = None
    pulse_trade_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    market_phase: Optional[str] = None
    data_status: Optional[str] = None
    run_action: Optional[str] = None
    non_trading: bool = False
    status_reason: Optional[str] = None
    no_trade_reasons: List[str] = Field(default_factory=list)
    recovery_conditions: List[str] = Field(default_factory=list)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    gate_state: Optional[str] = None
    gate_reasons: List[str] = Field(default_factory=list)
    recommendation_state: str = "NO_TRADE"
    explain_context: Dict[str, Any] = Field(default_factory=dict)
    decision_evidence_pack: Dict[str, Any] = Field(default_factory=dict)
    decision_context_snapshot_id: Optional[str] = None


class CanonicalPick(GPModel):
    symbol: str
    code: str
    name: Optional[str] = None
    rank: int
    action: str = "WATCH"
    execution_state: str = "WATCH_ONLY"
    can_execute_now: bool = False
    thesis: str = ""
    why_selected: str = ""
    entry_zone: Dict[str, Any] = Field(default_factory=dict)
    entry_text: Optional[str] = None
    stop: Optional[float] = None
    stop_text: Optional[str] = None
    invalidation: Optional[str] = None
    take_profit: List[float] = Field(default_factory=list)
    take_text: Optional[str] = None
    confidence: float = 0.0
    risk_level: str = "medium"
    score: float = 0.0
    final_score: float = 0.0
    live_score: float = 0.0
    daily_rank_score: float = 0.0
    exec_score: float = 0.0
    technical_basis: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    artifact_id: Optional[str] = None
    slot_id: Optional[str] = None
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    vwap: Optional[float] = None
    orb30_high: Optional[float] = None
    orb30_low: Optional[float] = None
    rs_index: Optional[float] = None
    rs_industry: Optional[float] = None
    slot_rel_vol: Optional[float] = None
    entry_distance_pct: Optional[float] = None
    recommendation_state: str = "UNAVAILABLE"
    champion_strategy: Optional[str] = None
    champion_strategy_score: float = 0.0
    strategy_reason_codes: List[str] = Field(default_factory=list)
    strategy_reject_reasons: List[str] = Field(default_factory=list)
    competing_strategies: List[Dict[str, Any]] = Field(default_factory=list)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)
    feature_snapshot: Dict[str, Any] = Field(default_factory=dict)
    raw_bar_summary: List[Dict[str, Any]] = Field(default_factory=list)
    execution_plan: Dict[str, Any] = Field(default_factory=dict)
    risk_pack: Dict[str, Any] = Field(default_factory=dict)
    explain_context: Dict[str, Any] = Field(default_factory=dict)
    signal: Dict[str, Any] = Field(default_factory=dict)
    probability: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)
    ranking: Dict[str, Any] = Field(default_factory=dict)
    historical_cases: List[Dict[str, Any]] = Field(default_factory=list)
    decision_context_snapshot_id: Optional[str] = None


class CanonicalRunArtifact(GPModel):
    run_id: str
    artifact_id: Optional[str] = None
    slot_id: Optional[str] = None
    book_version: Optional[str] = None
    as_of: str
    trading_day: str
    daybook_effective_day: Optional[str] = None
    pulse_trade_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    market_phase: Optional[str] = None
    slot_status: Optional[str] = None
    run_action: str = "NO_TRADE"
    recommendation_state: str = "NO_TRADE"
    tradeable: bool = False
    publish_allowed: bool = False
    non_trading: bool = False
    status_reason: Optional[str] = None
    no_trade_reasons: List[str] = Field(default_factory=list)
    recovery_conditions: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    picks: List[CanonicalPick] = Field(default_factory=list)
    gate: Dict[str, Any] = Field(default_factory=dict)
    data_quality: Dict[str, Any] = Field(default_factory=dict)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    explain_context: Dict[str, Any] = Field(default_factory=dict)
    decision_evidence_pack: Dict[str, Any] = Field(default_factory=dict)
    tool_trace: Dict[str, Any] = Field(default_factory=dict)
    decision_context_snapshot_id: Optional[str] = None


class LiveEntryDecisionArtifact(GPModel):
    symbol: str
    name: Optional[str] = None
    execution_state: str
    can_execute_now: bool = False
    next_action: str = ""
    summary: str = ""
    gate_state: Optional[str] = None
    gate_reasons: List[str] = Field(default_factory=list)
    vwap: Optional[float] = None
    orb30_high: Optional[float] = None
    orb30_low: Optional[float] = None
    entry_text: Optional[str] = None
    stop_text: Optional[str] = None
    take_text: Optional[str] = None
    entry_distance_pct: Optional[float] = None
    slot_rel_vol: Optional[float] = None
    rs_index: Optional[float] = None
    rs_industry: Optional[float] = None
    reason_codes: List[str] = Field(default_factory=list)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    source_run_id: Optional[str] = None
    explain_context: Dict[str, Any] = Field(default_factory=dict)
    quote_snapshot: Dict[str, Any] = Field(default_factory=dict)
    user_quote: Dict[str, Any] = Field(default_factory=dict)
    plan_position: Dict[str, Any] = Field(default_factory=dict)


class PickDetailArtifact(GPModel):
    symbol: str
    name: Optional[str] = None
    rank: Optional[int] = None
    thesis: str = ""
    why_selected: str = ""
    entry_text: Optional[str] = None
    stop_text: Optional[str] = None
    take_text: Optional[str] = None
    invalidation: Optional[str] = None
    execution_state: Optional[str] = None
    risk_level: str = "medium"
    reason_codes: List[str] = Field(default_factory=list)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    source_run_id: Optional[str] = None
    explain_context: Dict[str, Any] = Field(default_factory=dict)


class SingleStockAnalysisArtifact(GPModel):
    symbol: str
    name: Optional[str] = None
    as_of: Optional[str] = None
    last_date: Optional[str] = None
    data_status: Dict[str, Any] = Field(default_factory=dict)
    kline_summary: Dict[str, Any] = Field(default_factory=dict)
    champion: Dict[str, Any] = Field(default_factory=dict)
    trade_plan: Dict[str, Any] = Field(default_factory=dict)
    overall_state: str = "UNAVAILABLE"
    reason_codes: List[str] = Field(default_factory=list)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)


class NoTradeArtifact(GPModel):
    run_action: str = "NO_TRADE"
    market_summary: str = ""
    status_reason: str = ""
    no_trade_reasons: List[str] = Field(default_factory=list)
    recovery_conditions: List[str] = Field(default_factory=list)
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    source_run_id: Optional[str] = None


class ExitDecisionArtifact(GPModel):
    symbol: str
    action: str = "WATCH"
    reason: str = ""
    trigger: str = ""
    stop: Optional[float] = None
    invalidation: Optional[str] = None
    take_profit: List[float] = Field(default_factory=list)
    current_state: Optional[str] = None
    confidence: float = 0.0
    source_run_id: Optional[str] = None
    data_provenance: Dict[str, Any] = Field(default_factory=dict)


class CompareArtifact(GPModel):
    compared_symbols: List[str] = Field(default_factory=list)
    leader_symbol: Optional[str] = None
    ranking: List[Dict[str, Any]] = Field(default_factory=list)
    comparison_points: List[str] = Field(default_factory=list)
    source_run_id: Optional[str] = None
    data_provenance: Dict[str, Any] = Field(default_factory=dict)
    explain_context: Dict[str, Any] = Field(default_factory=dict)


class CandidateComparisonArtifact(GPModel):
    compared_symbols: List[str] = Field(default_factory=list)
    selected_symbol: Optional[str] = None
    selected_rank: Optional[int] = None
    selection_reason: str = ""
    rejected_symbols: List[str] = Field(default_factory=list)
    user_constraint: str = ""
    candidate_scope: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    source_run_id: Optional[str] = None
    model_reasoning_summary: Optional[str] = None


class IntradaySituationArtifact(GPModel):
    symbol: Optional[str] = None
    source: str = "unverified_user_input"
    verified: bool = False
    user_quote: Dict[str, Any] = Field(default_factory=dict)
    quote_snapshot: Dict[str, Any] = Field(default_factory=dict)
    live_entry: Optional[LiveEntryDecisionArtifact] = None
    summary: str = ""
    source_run_id: Optional[str] = None


class RunChangeArtifact(GPModel):
    current_run_id: Optional[str] = None
    previous_run_id: Optional[str] = None
    added: List[str] = Field(default_factory=list)
    removed: List[str] = Field(default_factory=list)
    rank_changes: List[Dict[str, Any]] = Field(default_factory=list)
    gating_change: Dict[str, Any] = Field(default_factory=dict)
    data_quality_change: Dict[str, Any] = Field(default_factory=dict)


class GroundingSummary(GPModel):
    market_phase: Optional[str] = None
    daily_target_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    repair_status: str = "ready"
    decision_basis_labels: List[str] = Field(default_factory=list)


class DecisionBasis(GPModel):
    labels: List[str] = Field(default_factory=list)
    market_phase: Optional[str] = None
    daily_target_day: Optional[str] = None
    pulse_slot_at: Optional[str] = None
    selection_reason: Optional[str] = None
    execution_reason: Optional[str] = None
    risk_notes: List[str] = Field(default_factory=list)
    repair_status: str = "ready"
    repair_stage: Optional[str] = None


class AgentToolResult(GPModel):
    tool_name: str
    reply_text: str = ""
    message: Dict[str, Any] = Field(default_factory=dict)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    grounding_summary: GroundingSummary = Field(default_factory=GroundingSummary)
    decision_basis: DecisionBasis = Field(default_factory=DecisionBasis)
    tool_trace: Dict[str, Any] = Field(default_factory=dict)


class AgentActionTrace(GPModel):
    selected_tools: List[str] = Field(default_factory=list)
    final_tool: Optional[str] = None
    max_tool_rounds: int = 3
    stopped_reason: str = "completed"
    reasoning_content_seen: bool = False
    errors: List[str] = Field(default_factory=list)


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
    canonical_run: Optional[CanonicalRunArtifact] = None
    subject_entry: Optional[BoardEntry] = None
    compare_entries: List[BoardEntry] = Field(default_factory=list)
    pick_detail: Optional[PickDetailArtifact] = None
    single_stock_analysis: Optional[SingleStockAnalysisArtifact] = None
    live_entry: Optional[LiveEntryDecisionArtifact] = None
    no_trade: Optional[NoTradeArtifact] = None
    exit_decision: Optional[ExitDecisionArtifact] = None
    compare_view: Optional[CompareArtifact] = None
    candidate_comparison: Optional[CandidateComparisonArtifact] = None
    intraday_situation: Optional[IntradaySituationArtifact] = None
    run_change_view: Optional[RunChangeArtifact] = None
    exit_view: Dict[str, Any] = Field(default_factory=dict)
    claims: List[Claim] = Field(default_factory=list)
    side_results: List[SideResult] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    diff: Dict[str, Any] = Field(default_factory=dict)


class ReplyBundle(GPModel):
    session_id: str
    text: str
    kind: Optional[str] = None
    run_id: Optional[str] = None
    symbols: List[str] = Field(default_factory=list)
    right_panel: Dict[str, Any] = Field(default_factory=dict)
    ui_items: List[Dict[str, Any]] = Field(default_factory=list)
    message: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    planner_trace: Dict[str, Any] = Field(default_factory=dict)
    grounding_summary: Dict[str, Any] = Field(default_factory=dict)
    decision_basis: Dict[str, Any] = Field(default_factory=dict)
    tool_trace: Dict[str, Any] = Field(default_factory=dict)
    agent_trace: Dict[str, Any] = Field(default_factory=dict)
