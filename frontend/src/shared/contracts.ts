// Chat contracts
export interface ChatRequest {
  session_id?: string
  message: string
}

// Canonical message model
export type CanonicalPick = {
  symbol: string
  name?: string | null
  rank: number
  action: 'BUY' | 'WATCH' | 'INVALID'
  state_label: string
  thesis?: string
  entry_text?: string
  stop_text?: string
  take_text?: string
  why_selected_text?: string
  reason_short?: string
  can_execute_now?: boolean
  missing_fields?: string[]
}

export type CanonicalRecommendMessage = {
  message_kind: 'recommend'
  lead_summary?: string
  decision_state?: 'BUY' | 'WATCH' | 'INVALID'
  market_summary?: string
  execution_note?: string
  risk_note?: string
  picks: CanonicalPick[]
  narrative_text: string
  followup_suggestions?: string[]
}

export type CanonicalFollowupMessage = {
  message_kind: 'followup' | 'compare' | 'exit' | 'no_trade' | 'explain' | 'live_check' | 'run_change' | 'chat'
  narrative_text: string
  state_tags?: Array<{ label: string; value: string }>
  symbols?: string[]
  reason?: string
  symbol?: string | null
  followup_suggestions?: string[]
}

export type CanonicalMessage = CanonicalRecommendMessage | CanonicalFollowupMessage

export interface ChatResponse {
  session_id: string
  reply: string
  message?: CanonicalMessage
  run_id?: string | null
  symbols: string[]
  right_panel: Record<string, unknown>
  ui_items: Array<Record<string, unknown>>
  planner_trace: Record<string, unknown>
  evidence_refs: string[]
}

// Health/book/run/session domain contracts
export interface HealthResponse {
  status: string
  trading_day?: string | null
  book_version?: string | null
  llm_ready: boolean
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
}

export interface BoardEntry {
  symbol: string
  name?: string | null
  rank: number
  final_score: number
  live_score: number
  execution_state: string
  can_open: boolean
  stretched: boolean
  invalidated: boolean
  summary: string
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

// Session list API
export interface SessionListItem {
  session_id: string
  created_at: string
  updated_at: string
  title: string
  preview: string
  active_run_id?: string | null
}
