export interface ChatRequest {
  session_id?: string
  message: string
  client_turn_id: string
}

export interface ChatResponse {
  session_id: string
  client_turn_id: string
  snapshot_id?: string | null
  decision: 'recommend' | 'no_trade'
  reply: string
  message: Record<string, unknown>
  symbols: string[]
}

export interface AgentTurn {
  turn_id: string
  seq: number
  role: 'user' | 'assistant'
  content: string
  snapshot_id: string
  payload: Record<string, unknown>
  created_at: string
}

export interface ChatHistoryResponse {
  session_id: string
  turns: AgentTurn[]
}

export interface HealthResponse {
  status: string
  agent_db: { sessions: number; turns: number; snapshots: number; current_snapshot_id?: string | null; path: string }
  current_snapshot?: { snapshot_id: string; schema_version: string; as_of: string; decision: string; tradeable: boolean; payload_hash: string } | null
  history_db: { path: string; exists: boolean; bytes: number }
  worker: { publisher: string }
}
