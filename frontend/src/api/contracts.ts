// Frozen API contracts for read-model (Phase 1)

export type ConversationSummary = {
  id: string
  title: string
  last_seq: number
  last_item_preview: string
  last_item_kind: 'text' | 'recommendation' | 'status'
  last_item_ts: string | null
  unread_count: number
  updated_at: string | null
}

export type ThreadBase = {
  id: string
  conversation_id: string
  seq: number
  created_at: string
  role: 'user' | 'assistant' | 'system'
}

export type TextItem = ThreadBase & {
  kind: 'text'
  content: string
}

export type RecommendationItem = ThreadBase & {
  kind: 'recommendation'
  artifact_id: string
  summary?: { total: number; top_symbols: string[] }
}

export type StatusItem = ThreadBase & {
  kind: 'status'
  code?: string
  message?: string
}

export type ThreadItem = TextItem | RecommendationItem | StatusItem

export type RecommendationArtifact = {
  id: string
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
}

export type SearchHit = {
  conversation_id: string
  seq: number
  message_id: string
  preview: string
  highlights?: Array<{ start: number; length: number }>
  anchor: { conversation_id: string; seq: number }
}

