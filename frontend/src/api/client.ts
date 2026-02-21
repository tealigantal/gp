import axios from 'axios'
import type { ChatReq, ChatResp, RecommendReq, RecommendResp, HealthResp, OHLCVResp, SyncReq, SyncResp, EventOut } from './types'

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
export async function sync(req: SyncReq) {
  const { data } = await api.post<SyncResp>('/sync', req)
  return data
}

export async function listEvents(cid: string, params: { after?: number; around?: number; limit?: number } = {}) {
  const { data } = await api.get<EventOut[]>(`/conversations/${encodeURIComponent(cid)}/events`, { params })
  return data
}

export async function search(params: { q: string; conversation_id?: string; limit?: number }) {
  const { data } = await api.get<Array<{ conversation_id: string; seq: number; message_id: string }>>('/search', { params })
  return data
}

export async function deleteConversation(cid: string) {
  const { data } = await api.delete<{ status: string }>(`/conversations/${encodeURIComponent(cid)}`)
  return data
}

export async function cleanupConversations(mode: 'all' | 'events_only' = 'all') {
  const { data } = await api.post<{ status: string; mode: string }>(`/conversations/cleanup`, { mode })
  return data
}
