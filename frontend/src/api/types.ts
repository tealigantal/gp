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
