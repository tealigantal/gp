import axios from 'axios'
import type { ChatReq, ChatResp, RecommendReq, RecommendResp, HealthResp, OHLCVResp, SyncReq, SyncResp, EventOut, RecommendV2, CompareResp, PickDetailResp, StrategyValidationResp, PaperfolioResp, LiveShadowResp, ValidationSummary, PortfolioState, ExecutionEvent, OrderIntent, WorkbenchSnapshot } from './types'
import type { ConversationSummary, ThreadItem, RecommendationArtifact, SearchHit } from './contracts'

const baseURL = import.meta.env.VITE_API_BASE || '/api'

export const api = axios.create({ baseURL })

// 统一错误处理：抛出更友好的错误消息
api.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error?.response?.status
    const detail = error?.response?.data?.detail || error?.message || '请求失败'
    const msg = status ? `${status}: ${detail}` : String(detail)
    return Promise.reject(new Error(msg))
  }
)

export async function chat(body: ChatReq) {
  const { data } = await api.post<ChatResp>('/chat', body)
  return data
}

export async function setChatFocus(body: { session_id?: string | null; focus_symbol: string }) {
  const { data } = await api.post<{ ok: boolean; session_id: string; focus_symbol: string; state: Record<string, unknown> }>('/chat/focus', body)
  return data
}

export async function recommend(body: RecommendReq) {
  const { data } = await api.post<RecommendResp>('/recommend', body)
  return data
}

export async function health() {
  const { data } = await api.get<HealthResp>('/health')
  return data
}

export async function ohlcv(symbol: string, params?: { start?: string; end?: string; limit?: number }) {
  const { data } = await api.get<OHLCVResp>(`/ohlcv/${symbol}`, { params })
  return data
}

// --- Events/sync APIs ---
export async function sync(req: SyncReq, opts: { signal?: AbortSignal; headers?: Record<string, string> } = {}) {
  const { data } = await api.post<SyncResp>('/sync', req, { signal: opts.signal, headers: opts.headers })
  return data
}

export async function listEvents(cid: string, params: { after?: number; around?: number; limit?: number } = {}, opts: { signal?: AbortSignal } = {}) {
  const { data } = await api.get<EventOut[]>(`/conversations/${encodeURIComponent(cid)}/events`, { params, signal: opts.signal })
  return data
}

// Legacy search (kept for existing UI)
export async function search(params: { q: string; conversation_id?: string; limit?: number }) {
  const { data } = await api.get<Array<{ conversation_id: string; seq: number; message_id: string }>>('/search_legacy', { params })
  return data
}

export async function deleteConversation(cid: string) {
  const { data } = await api.delete<{ status: string }>(`/conversations/${encodeURIComponent(cid)}`,
    { headers: { 'X-Delete-Reason': 'user_click' } })
  return data
}

// -------- New read-model API (Phase 1) --------

export async function getConversationSummaries() {
  const { data } = await api.get<ConversationSummary[]>('/conversations/summaries')
  return data
}

export async function getThreadItems(conversationId: string, params: { anchor?: number; direction?: 'backward' | 'forward'; limit?: number } = {}) {
  const { data } = await api.get<ThreadItem[]>(`/threads/${encodeURIComponent(conversationId)}/items`, { params })
  return data
}

export async function postThreadRead(conversationId: string, body: { last_read_seq: number }) {
  const { data } = await api.post<{ status: string }>(`/threads/${encodeURIComponent(conversationId)}/read`, body)
  return data
}

export async function getRecommendationArtifact(artifactId: string) {
  const { data } = await api.get<RecommendationArtifact>(`/artifacts/recommendations/${encodeURIComponent(artifactId)}`)
  return data
}

export async function searchHits(params: { q: string; conversation_id?: string; limit?: number }) {
  const { data } = await api.get<SearchHit[]>('/search', { params })
  return data
}

export async function cleanupConversations(mode: 'all' | 'events_only' = 'all') {
  const { data } = await api.post<{ status: string; mode: string }>(`/conversations/cleanup`, { mode },
    { headers: { 'X-Delete-Reason': 'user_click_cleanup_all' } })
  return data
}

// ---- Phase 2.6: minimal V2 read-only client ----

export async function getRecommendV2(params: { run_id?: string; as_of?: string } = {}) {
  // internal/raw read; prefer getRecommendV2Gated for user-visible surfaces
  const { data } = await api.get<RecommendV2>('/recommend_v2', { params })
  return data
}

export async function getRecommendV2Gated(params: { run_id?: string; as_of?: string } = {}) {
  const { data } = await api.get<RecommendV2>('/recommend_v2/gated', { params })
  return data
}

// compareSymbols is no longer exposed in the primary UI

export async function getPickDetail(params: { run_id?: string; symbol: string }) {
  const { data } = await api.get<PickDetailResp>('/pick', { params })
  return data
}

// ---- Validation + Live Shadow ----

export async function getStrategyValidation(strategy: string) {
  const { data } = await api.get<StrategyValidationResp>(`/validation/strategy/${encodeURIComponent(strategy)}`)
  return data
}

export async function getPaperfolio() {
  const { data } = await api.get<PaperfolioResp>('/paperfolio')
  return data
}

export async function getLiveShadowSummary() {
  const { data } = await api.get<LiveShadowResp>('/live_shadow/summary')
  return data
}

export async function getValidationSummary() {
  const { data } = await api.get<ValidationSummary>('/validation/summary')
  return data
}

// ---- Phase 7: Execution/Portfolio ----
export async function getPortfolio() {
  const { data } = await api.get<PortfolioState>('/portfolio')
  return data
}

export async function getExecutionEvents(limit = 100) {
  const { data } = await api.get<ExecutionEvent[]>('/execution/events', { params: { limit } })
  return data
}

export async function runPaperExecution(params: { run_id?: string; as_of?: string } = {}) {
  const { data } = await api.post<{ ok: boolean; admitted?: number; events?: number; error?: string }>(`/execution/paper/run`, null, { params })
  return data
}

// ---- Phase 8: Workbench + Operator actions ----
export async function getWorkbench(params: { run_id?: string; as_of?: string; event_limit?: number } = {}) {
  const { data } = await api.get<WorkbenchSnapshot>('/workbench', { params })
  return data
}

export async function postOperatorIntentAction(body: { action: 'admit'|'reject'|'cancel'; run_id?: string; as_of?: string; symbol?: string; intent_id?: string; operator_note?: string }) {
  const { data } = await api.post<{ ok: boolean; error?: string; intent_id?: string }>(`/operator/intent/action`, body)
  return data
}
