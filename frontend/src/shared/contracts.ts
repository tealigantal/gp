export interface ChatRequest {
  session_id?: string
  message: string
}

export type ExecutionState =
  | 'PLAN_READY'
  | 'BUY_NOW'
  | 'WAIT_PULLBACK'
  | 'WAIT_NEXT_SESSION'
  | 'WATCH_ONLY'
  | 'RISK_HIGH'
  | 'INVALIDATED'
  | 'UNAVAILABLE'

export interface CanonicalPick {
  symbol: string
  code: string
  name?: string | null
  rank: number
  action: 'BUY' | 'WATCH'
  execution_state: ExecutionState
  can_execute_now: boolean
  thesis?: string
  why_selected?: string
  entry_text?: string | null
  stop_text?: string | null
  take_text?: string | null
  invalidation?: string | null
  confidence?: number
  risk_level?: string
  score?: number
  final_score?: number
  live_score?: number
  daily_rank_score?: number
  exec_score?: number
  technical_basis?: string[]
  reason_codes?: string[]
  missing_fields?: string[]
  artifact_id?: string | null
  slot_id?: string | null
  vwap?: number | null
  orb30_high?: number | null
  orb30_low?: number | null
  rs_index?: number | null
  rs_industry?: number | null
  slot_rel_vol?: number | null
  entry_distance_pct?: number | null
  data_provenance?: Record<string, unknown>
}

export interface CanonicalRunArtifact {
  run_id: string
  artifact_id?: string | null
  book_version?: string | null
  as_of: string
  trading_day: string
  daybook_effective_day?: string | null
  pulse_trade_day?: string | null
  pulse_slot_at?: string | null
  market_phase?: string | null
  slot_status?: string | null
  run_action: 'RECOMMEND' | 'NO_TRADE' | 'DEGRADED'
  tradeable: boolean
  publish_allowed: boolean
  non_trading: boolean
  status_reason?: string | null
  no_trade_reasons: string[]
  recovery_conditions: string[]
  themes: string[]
  picks: CanonicalPick[]
  gate: Record<string, unknown>
  data_quality: Record<string, unknown>
  data_provenance: Record<string, unknown>
  tool_trace: Record<string, unknown>
}

export interface LiveEntryDecision {
  symbol: string
  name?: string | null
  execution_state: ExecutionState
  can_execute_now: boolean
  next_action: string
  summary: string
  gate_state?: string | null
  gate_reasons?: string[]
  vwap?: number | null
  orb30_high?: number | null
  orb30_low?: number | null
  entry_text?: string | null
  stop_text?: string | null
  take_text?: string | null
  entry_distance_pct?: number | null
  slot_rel_vol?: number | null
  rs_index?: number | null
  rs_industry?: number | null
  reason_codes?: string[]
  data_provenance?: Record<string, unknown>
  source_run_id?: string | null
}

export interface PickDetailArtifact {
  symbol: string
  name?: string | null
  rank?: number | null
  thesis: string
  why_selected: string
  entry_text?: string | null
  stop_text?: string | null
  take_text?: string | null
  invalidation?: string | null
  execution_state?: ExecutionState | null
  risk_level?: string
  reason_codes?: string[]
  data_provenance?: Record<string, unknown>
  source_run_id?: string | null
}

export interface SingleStockAnalysisArtifact {
  symbol: string
  name?: string | null
  as_of?: string | null
  last_date?: string | null
  data_status: Record<string, unknown>
  kline_summary: Record<string, unknown>
  champion: Record<string, unknown>
  trade_plan: Record<string, unknown>
  overall_state: string
  reason_codes: string[]
  data_provenance: Record<string, unknown>
}

export interface ExitDecisionArtifact {
  symbol: string
  action: 'HOLD' | 'REDUCE' | 'SELL' | 'WATCH'
  reason: string
  trigger: string
  stop?: number | null
  invalidation?: string | null
  take_profit?: number[]
  current_state?: ExecutionState | string | null
  confidence?: number
  source_run_id?: string | null
  data_provenance?: Record<string, unknown>
}

export interface CompareArtifact {
  compared_symbols: string[]
  leader_symbol?: string | null
  ranking: Array<Record<string, unknown>>
  comparison_points: string[]
  source_run_id?: string | null
  data_provenance?: Record<string, unknown>
}

export interface RunChangeArtifact {
  current_run_id?: string | null
  previous_run_id?: string | null
  added: string[]
  removed: string[]
  rank_changes: Array<Record<string, unknown>>
  gating_change: Record<string, unknown>
  data_quality_change: Record<string, unknown>
}

export interface CanonicalRecommendMessage {
  message_kind: 'recommend'
  narrative_text: string
  lead_summary?: string
  decision_state?: 'BUY' | 'WATCH'
  market_summary?: string
  execution_note?: string | null
  risk_note?: string | null
  picks: CanonicalPick[]
  run: CanonicalRunArtifact
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalNoTradeMessage {
  message_kind: 'no_trade'
  narrative_text: string
  run?: CanonicalRunArtifact | null
  market_summary?: string
  reason?: string
  no_trade_reasons?: string[]
  recovery_conditions?: string[]
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalPickDetailMessage {
  message_kind: 'pick_detail'
  narrative_text: string
  pick: PickDetailArtifact
  run?: CanonicalRunArtifact | null
  symbol?: string | null
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalSingleStockQueryMessage {
  message_kind: 'single_stock_query'
  narrative_text: string
  analysis: SingleStockAnalysisArtifact
  symbol?: string | null
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalLiveEntryMessage {
  message_kind: 'live_entry_check'
  narrative_text: string
  live_check: LiveEntryDecision
  run?: CanonicalRunArtifact | null
  symbol?: string | null
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalCompareMessage {
  message_kind: 'compare'
  narrative_text: string
  compare: CompareArtifact
  run?: CanonicalRunArtifact | null
  symbols?: string[]
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalExitDecisionMessage {
  message_kind: 'exit_decision'
  narrative_text: string
  exit_decision: ExitDecisionArtifact
  run?: CanonicalRunArtifact | null
  symbol?: string | null
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalRunChangeMessage {
  message_kind: 'run_change'
  narrative_text: string
  run_change: RunChangeArtifact
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalChatMessage {
  message_kind: 'chat'
  narrative_text: string
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export interface CanonicalTermExplainMessage {
  message_kind: 'term_explain'
  narrative_text: string
  term?: string
  source_message_kind?: string
  followup_suggestions?: string[]
  freshness_meta?: Record<string, unknown>
}

export type CanonicalMessage =
  | CanonicalRecommendMessage
  | CanonicalNoTradeMessage
  | CanonicalPickDetailMessage
  | CanonicalSingleStockQueryMessage
  | CanonicalLiveEntryMessage
  | CanonicalCompareMessage
  | CanonicalExitDecisionMessage
  | CanonicalRunChangeMessage
  | CanonicalTermExplainMessage
  | CanonicalChatMessage

export interface ChatResponse {
  session_id: string
  reply: string
  message?: CanonicalMessage
  run_id?: string | null
  symbols: string[]
  right_panel: Record<string, unknown>
  ui_items: Array<Record<string, unknown>>
  grounding_summary: {
    market_phase?: string | null
    daily_target_day?: string | null
    pulse_slot_at?: string | null
    repair_status: string
    decision_basis_labels: string[]
  }
}

export interface HealthStorageStats {
  session_count: number
  transcript_count: number
  claim_count: number
  latest_session_at?: string | null
}

export interface RuntimeToolInfo {
  service: string
  mode: 'always_on' | 'manual' | string
  command: string
  description: string
  profile?: string | null
}

export interface RuntimeStatus {
  market_phase: string
  data_provider: string
  auto_update_service: string
  auto_update_expected: boolean
  intraday_runtime_enabled?: boolean
  worker_poll_interval_sec: number
  book_freshness: string
  book_updated_at?: string | null
  artifact_id?: string | null
  daybook_effective_day?: string | null
  pulse_trade_day?: string | null
  pulse_slot_at?: string | null
  last_closed_5m?: string | null
  slot_status?: string | null
  publish_allowed: boolean
  repair_status: string
  repair_stage: string
  daily_freshness_ready?: boolean
  daily_target_day?: string | null
  daily_target_mode?: 'previous_completed' | 'current_ready' | 'current_pending' | string
  pending_eod_day?: string | null
  eod_probe?: {
    ready?: boolean
    checked_at?: string | null
    ok_count?: number
    next_retry_after?: string | null
    error?: string | null
  } | null
  daily_checked_count?: number
  daily_stale_count?: number
  daily_last_reconcile_at?: string | null
  daily_blocking_reason?: string | null
  daily_failed_symbols?: string[]
  pulse_target_trade_day?: string | null
  pulse_target_slot_at?: string | null
  last_repair_started_at?: string | null
  last_repair_finished_at?: string | null
  blocking_reason?: string | null
  artifact_status: string
  services: RuntimeToolInfo[]
}

export interface OpsRunResponse {
  operation: string
  status: string
  message: string
  executed_at?: string | null
  result: Record<string, unknown>
  runtime: RuntimeStatus
}

export interface HealthResponse {
  status: string
  trading_day?: string | null
  book_version?: string | null
  llm_ready: boolean
  storage: HealthStorageStats
  runtime: RuntimeStatus
}

export interface SessionState {
  session_id: string
  created_at: string
  updated_at: string
  active_run_id?: string | null
  previous_run_id?: string | null
  focus_subject: Record<string, unknown>
  compare_set: string[]
  user_preferences: Record<string, unknown>
  last_seen_book_version?: string | null
  last_turn_id?: string | null
  last_claim_ids: string[]
}

export interface TranscriptEvent {
  seq: number
  turn_id: string
  session_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  meta: Record<string, unknown>
}

export interface Claim {
  claim_id: string
  session_id: string
  subject_type: string
  subject_id: string
  predicate: string
  value: Record<string, unknown>
  evidence_refs: string[]
  turn_id: string
  created_at: string
}

export interface SessionResponse {
  session: SessionState
  recent_turns: TranscriptEvent[]
  recent_claims: Claim[]
}

export interface SessionDiagnosticsResponse {
  session_id: string
  focus: {
    active_run_id?: string | null
    previous_run_id?: string | null
    last_focus_symbol?: string | null
    last_focus_rank?: number | null
    compare_set: string[]
  }
  latest_assistant?: {
    turn_id?: string
    seq?: number
    created_at?: string
    message_kind?: string
    narrative_text?: string
    symbol?: string | null
    run_action?: string | null
    followup_suggestions?: string[]
  } | null
  assistant_messages: Array<{
    turn_id?: string
    seq?: number
    created_at?: string
    message_kind?: string
    narrative_text?: string
    symbol?: string | null
    run_action?: string | null
    followup_suggestions?: string[]
  }>
}

export interface AdvicePick {
  symbol: string
  name?: string | null
  rank: number
  strategy_id?: string | null
  thesis: string
  entry_plan: Record<string, unknown>
  stop_plan: Record<string, unknown>
  take_profit_plan: Record<string, unknown>
  scores: Record<string, number>
  risk_flags: string[]
  why_selected: string
  why_not_others: string[]
  evidence_refs: string[]
  style_label?: string | null
}

export interface SymbolPulse {
  symbol: string
  last_bar_at?: string | null
  pulse_score: number
  momentum_state: string
  stretch_state: string
  liquidity_state: string
  execution_state: string
  invalidated: boolean
  entry_distance_pct?: number | null
  flags: string[]
  evidence_refs: string[]
  live_score?: number
  daily_rank_score?: number
  exec_score?: number
  action?: string
  can_open?: boolean
  signal_type?: string
  trade_day?: string | null
  slot_at?: string | null
}

export interface BoardEntry {
  symbol: string
  name?: string | null
  rank: number
  final_score: number
  live_score: number
  daily_rank_score?: number
  exec_score?: number
  action?: string
  execution_state: string
  can_open: boolean
  stretched: boolean
  extended?: boolean
  invalidated: boolean
  signal_type?: string
  entry_zone?: Record<string, unknown>
  stop?: number | null
  take?: number[]
  vwap?: number | null
  orb30_high?: number | null
  orb30_low?: number | null
  rs_index?: number | null
  rs_industry?: number | null
  slot_rel_vol?: number | null
  summary: string
  reason_codes?: string[]
  artifact_id?: string | null
  slot_id?: string | null
  style_label?: string | null
  pick: AdvicePick
  pulse?: SymbolPulse | null
}

export interface SideResult {
  event_id: string
  created_at: string
  symbol?: string | null
  kind: string
  title: string
  body: string
  refs: Record<string, unknown>
}

export interface DayBook {
  trading_day: string
  generated_at: string
  regime: Record<string, unknown>
  tradeable: boolean
  reason?: string | null
  themes: string[]
  picks: AdvicePick[]
  reserve_symbols: string[]
  source_meta: Record<string, unknown>
}

export interface MarketBook {
  trading_day: string
  book_version: string
  updated_at: string
  regime: Record<string, unknown>
  daybook: DayBook
  board: BoardEntry[]
  watchset: string[]
  symbol_states: Record<string, SymbolPulse>
  portfolio_snapshot: Record<string, unknown>
  last_closed_5m?: string | null
  daybook_effective_day?: string | null
  pulse_trade_day?: string | null
  pulse_slot_at?: string | null
  market_phase?: string | null
  data_status?: string | null
  artifact_id?: string | null
  slot_id?: string | null
  slot_status?: string | null
  publish_allowed?: boolean
  side_results: SideResult[]
}

export interface AdviceRun {
  run_id: string
  session_id: string
  book_version: string
  created_at: string
  trading_day: string
  regime: Record<string, unknown>
  tradeable: boolean
  reason?: string | null
  picks: BoardEntry[]
  evidence_refs: string[]
}

export interface BookResponse {
  book: MarketBook
}

export interface RunResponse {
  run: AdviceRun
}

export interface SessionListItem {
  session_id: string
  created_at: string
  updated_at: string
  title: string
  preview: string
  active_run_id?: string | null
}
