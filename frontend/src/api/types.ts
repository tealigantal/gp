export type ToolTrace = {
  triggered_recommend: boolean
  recommend_result?: any
  error?: string
}

export type ChatReq = {
  session_id?: string | null
  message: string
}

export type ChatResp = {
  session_id?: string
  reply: string
  tool_trace: ToolTrace
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
  env?: { grade?: string; reasons?: string[]; recovery_conditions?: string[]; [k: string]: any }
  themes?: Array<{ name: string; strength?: number; [k: string]: any }>
  picks?: Array<any>
  tradeable?: boolean
  message?: string
  execution_checklist?: string[]
  disclaimer?: string
  debug?: { degraded?: boolean; degrade_reasons?: Array<{ reason_code: string; detail?: any }>; advisories?: any; [k: string]: any }
  [k: string]: any
}

export type HealthResp = { status: string; llm_ready: boolean; provider: any; time: string }

export type OHLCVBar = { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number }
export type OHLCVResp = { symbol: string; meta: any; bars: OHLCVBar[] }

// --- Events/Sync ---
export type EventOut = {
  id: string
  conversation_id: string
  seq: number
  type: string
  actor_id?: string | null
  created_at: string
  data: Record<string, any>
}

export type SyncEventIn = {
  id: string
  conversation_id: string
  type: string
  data: Record<string, any>
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
  conversations_delta: Array<Record<string, any>>
  user_settings_delta: Array<Record<string, any>>
}
