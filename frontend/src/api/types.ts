export type ToolTrace = {
  triggered_recommend: boolean
  recommend_result?: unknown
  error?: string
}

export type ChatReq = {
  session_id?: string | null
  message: string
  message_id?: string
}

export type ChatResp = {
  session_id?: string
  reply: string
  tool_trace: ToolTrace
  assistant_message_id?: string
  // Phase 1 additions (optional)
  run_id?: string
  symbols?: string[]
  fallback_used?: boolean
}

export type RecommendReq = {
  date?: string | null
  topk?: number
  universe?: 'auto' | 'symbols'
  symbols?: string[] | null
  risk_profile?: string
  detail?: 'compact' | 'full'
}

export type RecommendResp = {
  as_of?: string
  timezone?: string
  env?: { grade?: string; reasons?: string[]; recovery_conditions?: string[]; [k: string]: unknown }
  themes?: Array<{ name: string; strength?: number; [k: string]: unknown }>
  mainline?: { indicator?: string; sectors?: Array<unknown>; [k: string]: unknown }
  picks?: Array<unknown>
  tradeable?: boolean
  message?: string
  execution_checklist?: string[]
  disclaimer?: string
  debug?: { degraded?: boolean; degrade_reasons?: Array<{ reason_code: string; detail?: unknown }>; advisories?: unknown; [k: string]: unknown }
  [k: string]: unknown
}

export type HealthResp = { status: string; llm_ready: boolean; provider: unknown; time: string }

export type OHLCVBar = { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number }
export type OHLCVResp = { symbol: string; meta: unknown; bars: OHLCVBar[] }

// --- Events/Sync ---
export type EventOut = {
  id: string
  conversation_id: string
  seq: number
  type: string
  actor_id?: string | null
  created_at: string
  data: Record<string, unknown>
}

export type SyncEventIn = {
  id: string
  conversation_id: string
  type: string
  data: Record<string, unknown>
  actor_id?: string | null
  created_at?: string | null
}

export type SyncReq = {
  device_id: string
  conv_cursors: Record<string, number>
  outbox_events: SyncEventIn[]
}

export type SyncResp = {
  ack: Record<string, string>
  deltas: Record<string, EventOut[]>
  conversations_delta: Array<Record<string, unknown>>
  user_settings_delta: Array<Record<string, unknown>>
}

// ---- V2 (read-only, canonical) ----
export type PickV2Item = {
  pick_id: string
  symbol: string
  name?: string
  strategy?: string
  strategy_label?: string
  thesis?: string
  price_ref?: number
  entry_zone?: [number, number]
  stop?: number
  take_profit?: number[]
  reward_risk?: number
  execution_state?: 'actionable' | 'waiting_pullback' | 'observe_only' | 'below_support' | 'breakdown_risk'
  actionable?: boolean
  alpha_score?: number
  execution_score?: number
  reliability_score?: number
  final_score?: number
  confidence?: number
  signal_age_days?: number
  liquidity_grade?: 'A' | 'B' | 'C'
  volatility_grade?: 'low' | 'medium' | 'high'
  risk_flags?: string[]
  invalidation?: string[]
  notes?: string
  evidence?: { available: boolean; status: string; [k: string]: unknown }
  gating_decision?: {
    decision: 'allow' | 'degraded' | 'blocked'
    reasons?: string[]
    triggered_rules?: string[]
    warnings?: string[]
  }
}

export type RecommendV2 = {
  artifact_version: 'v2'
  run_id?: string | null
  as_of?: string | null
  snapshot_id?: string | null
  market_regime?: string | null
  degraded: boolean
  tradeable: boolean
  reason?: string | null
  risk_profile?: string | null
  universe_name?: string | null
  symbols: string[]
  themes: string[]
  items: PickV2Item[]
  fallback_used?: boolean
  errors?: string[]
  run_gating?: {
    decision: 'allow' | 'degraded' | 'blocked'
    reasons?: string[]
    warnings?: string[]
  }
}

// Phase 3/4: validation + live shadow
export type StrategyValidationResp = {
  strategy: string
  event_stats: Record<string, unknown>
  walk_forward: Record<string, unknown>
  strategy_health: Record<string, unknown>
}

export type PaperfolioResp = { available: boolean; picks: Array<Record<string, unknown>> }

export type LiveShadowResp = {
  available: boolean
  dates: string[]
  latest_date?: string | null
  summary?: { files?: string[]; sample?: unknown }
}

export type ValidationSummary = {
  as_of?: string | null
  parts: Record<string, unknown>
}

// ---- Phase 7: Execution/Portfolio ----
export type OrderIntent = {
  intent_id: string
  run_id?: string
  as_of?: string
  symbol: string
  side: 'buy' | 'sell'
  status: 'proposed' | 'admitted' | 'rejected' | 'executed' | 'expired' | 'cancelled'
  priority: number
  sizing_hint?: number
  gating_decision?: { decision: 'allow' | 'degraded' | 'blocked'; reasons?: string[] }
}

export type ExecutionEvent = {
  event_id: string
  intent_id: string
  event_type: 'created' | 'admitted' | 'rejected' | 'paper_filled' | 'cancelled' | 'expired'
  timestamp: string
  symbol: string
  notes?: string
}

export type PortfolioState = {
  as_of?: string
  positions: Array<Record<string, unknown>>
  pending_intents: OrderIntent[]
  recent_events: ExecutionEvent[]
}

// ---- Phase 8: Workbench Snapshot ----
export type WorkbenchSnapshot = {
  as_of?: string | null
  recommend: RecommendV2 | Record<string, unknown>
  validation_summary: ValidationSummary
  portfolio: PortfolioState
  intents_preview: OrderIntent[]
  execution_events: ExecutionEvent[]
  live_shadow_summary: { available: boolean; dates: string[]; latest_date?: string | null; summary?: unknown }
  warnings: string[]
  source_status: Record<string, unknown>
}

// Minimal compare/pick detail read-only contracts
export type CompareResp = {
  ok: boolean
  artifact_version?: 'v2'
  run_id?: string | null
  symbols: string[]
  items?: Record<string, unknown>[]
  ranking?: string[]
  winner_symbol?: string | null
  summary?: string | null
  degraded?: boolean
  fallback_used?: boolean
  errors?: string[]
  error?: string
}

export type PickDetailResp = {
  ok: boolean
  artifact_version?: 'v2'
  run_id?: string | null
  as_of?: string | null
  degraded?: boolean
  fallback_used?: boolean
  item?: Record<string, unknown> | null
  error?: string
}
