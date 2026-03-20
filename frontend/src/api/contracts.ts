// Frozen API contracts for read-model (Phase 1)

export type ConversationSummary = {
  id: string
  title: string
  last_seq: number
  last_item_preview: string
  last_item_kind: 'text' | 'assistant_bundle'
  last_item_ts: string | null
  unread_count: number
  updated_at: string | null
}

export type ThreadBase = {
  id: string
  conversation_id: string
  seq: number
  created_at: string
  role: 'user' | 'assistant'
}

export type TextItem = ThreadBase & {
  kind: 'text'
  content: string
}

export type CardVM = {
  type: 'recommendation' | 'selection_explain' | 'no_trade' | 'pick_detail' | 'compare' | 'exit_decision' | 'run_change'
  title: string
  data: Record<string, unknown>
  focus_symbol?: string
  symbols?: string[]
  run_id?: string
}

export type AssistantBundle = {
  kind: 'assistant_bundle'
  text: string
  cards: CardVM[]
  right_panel: Record<string, unknown>
  tool_calls: Array<Record<string, unknown>>
  tool_results: Array<Record<string, unknown>>
  grounding: {
    source: 'tool_calling_agent'
    active_run_id?: string | null
    previous_run_id?: string | null
    focus_symbol?: string | null
    active_symbols?: string[]
    used_symbols?: string[]
    tradeable?: boolean
    run_gating?: Record<string, unknown>
    tools_used?: string[]
  }
}

export type AssistantBundleItem = ThreadBase & {
  kind: 'assistant_bundle'
  bundle: AssistantBundle
}

export type ThreadItem = TextItem | AssistantBundleItem

export type RecommendationArtifact = {
  id: string
  // V2-aware metadata (when available)
  artifact_version?: 'v2'
  run_id?: string | null
  source?: string
  summary?: { total: number; top_symbols: string[]; tradeable?: boolean; market_regime?: string; reason?: string; run_gating?: { decision: 'allow' | 'degraded' | 'blocked'; reasons?: string[]; warnings?: string[] } }
  // legacy compatibility
  as_of: string | null
  timezone: string
  picks: Array<{
    symbol: string
    name?: string
    theme?: string
    champion?: { strategy: string; score?: number }
    trade_plan?: {
      entry?: string[] | string
      take?: string[] | string
      stop?: string
      bands?: { S1?: number; S2?: number; R1?: number; R2?: number }
      actions?: { window_A?: string; window_B?: string }
      risk?: { stop_loss?: string; time_stop?: string; no_averaging_down?: boolean }
    }
    chip?: { model_used?: string }
  }>
  tradeable?: boolean
  disclaimer?: string | null
  message?: string | null
  meta?: { env_grade?: string }
  diagnostics?: { degraded?: boolean; degrade_reasons?: Array<{ reason_code: string; detail?: unknown }> }
  // attached canonical v2 artifact for decision-chain UI (when artifact_version==='v2')
  v2?: import('./types').RecommendV2
}

export type SearchHit = {
  conversation_id: string
  seq: number
  message_id: string
  preview: string
  highlights?: Array<{ start: number; length: number }>
  anchor: { conversation_id: string; seq: number }
}
