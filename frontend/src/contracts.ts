export interface HealthStatus {
  current_publication_id: string | null
  plan_id: string | null
  runtime_id: string | null
  market_session_date: string | null
  daily_evidence_date: string | null
  slot_closed_at: string | null
  market_phase: string | null
  daily_data_state: string | null
  runtime_data_state: string | null
  publication_state: string | null
  tradeability_state: string | null
  market_recovery?: {
    state: string
    target_trade_date: string | null
    completed: number
    total: number
    failed: number
    next_retry_at: string | null
    approximate_universe: boolean
  }
  market_now?: {
    observed_at: string
    market_phase: string
    market_phase_label: string
    plan_relation: 'missing' | 'expired' | 'future' | 'preopen' | 'active' | 'inactive' | string
    tradeable_now: boolean
  }
  next_plan_target?: {
    observed_at: string
    market_session_date: string | null
    required_daily_evidence_date: string | null
    state: 'published' | 'ready_to_publish' | 'pending_daily_evidence' | 'unavailable' | string
    completed: number
    total: number
    failed: number
    next_retry_at: string | null
    approximate_universe: boolean
  }
}

export interface TradePlan {
  entry_low: number | null
  entry_high: number | null
  stop_price: number | null
  take_profit_prices: number[]
  action: string
  reason_codes: string[]
}

export interface CandidateDecision {
  symbol: string
  name: string
  disposition: 'selected' | 'reserve' | 'rejected' | string
  adaptive_score: number
  recommendation_strength: string
  signal: { score: number; label: string; reason_codes: string[] }
  probability: { probability: number; confidence: number; effective_sample_size: number; uncertainty: number }
  risk: { score: number; execution_risk: number; reason_codes: string[] }
  ranking: { score: number; rank: number; reason_codes: string[] }
  trade_plan: TradePlan
  reason_codes: string[]
}

export interface RecommendationPublication {
  publication_id: string
  plan_id: string
  runtime_id: string | null
  published_at: string
  decision: {
    plan_status: string
    execution_status: string
    tradeable_now: boolean
    reason_codes: string[]
  }
  candidates: CandidateDecision[]
  lineage: { plan_id: string; runtime_id: string | null; producer_revision: string; source_digest: string }
}

export interface ConversationSession {
  session_id: string
  active_publication_id: string
  created_at: string
  updated_at: string
}

export interface ConversationTurn {
  turn_id: string
  session_id: string
  publication_id: string
  sequence: number
  role: string
  content: string
  created_at: string
  client_turn_id: string | null
}

export interface ConversationDetail {
  session: ConversationSession
  turns: ConversationTurn[]
}

export interface ChatResponse {
  session_id: string
  client_turn_id: string
  publication_id: string
  reply: string
  publication: RecommendationPublication
}
