import axios from 'axios'
import type { ChatReq, ChatResp, RecommendReq, RecommendResp, HealthResp, OHLCVResp, SyncReq, SyncResp, EventOut } from './types'
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
