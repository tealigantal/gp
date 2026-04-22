import axios, { AxiosError } from 'axios'
import type {
  BookResponse,
  ChatRequest,
  ChatResponse,
  HealthResponse,
  RunResponse,
  SessionResponse,
  SessionListItem,
  SideResult,
} from './contracts'

const DEFAULT_API_TIMEOUT_MS = 60_000
const rawChatTimeout = Number(import.meta.env.VITE_CHAT_TIMEOUT_MS ?? '0')
const CHAT_TIMEOUT_MS = Number.isFinite(rawChatTimeout) && rawChatTimeout >= 0 ? rawChatTimeout : 0

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: DEFAULT_API_TIMEOUT_MS,
})

export async function getHealth() {
  const { data } = await api.get<HealthResponse>('/api/health')
  return data
}

export async function getCurrentBook() {
  const { data } = await api.get<BookResponse>('/api/book/current')
  return data
}

export async function getSession(sessionId: string) {
  const { data } = await api.get<SessionResponse>(`/api/session/${encodeURIComponent(sessionId)}`)
  return data
}

export async function getRun(runId: string) {
  const { data } = await api.get<RunResponse>(`/api/run/${encodeURIComponent(runId)}`)
  return data
}

export async function getSideResults() {
  const { data } = await api.get<SideResult[]>('/api/side-results')
  return data
}

export async function getSessions(limit = 20) {
  const { data } = await api.get<SessionListItem[]>(`/api/sessions?limit=${limit}`)
  return data
}

export async function postChat(payload: ChatRequest) {
  const { data } = await api.post<ChatResponse>('/api/chat', payload, {
    // Chat can legitimately take much longer than the normal dashboard requests.
    timeout: CHAT_TIMEOUT_MS,
  })
  return data
}

export function readApiError(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.code === AxiosError.ECONNABORTED) {
      return '对话请求超时。后端可能仍在处理中，请稍后查看会话结果，或增大 VITE_CHAT_TIMEOUT_MS。'
    }
    const payload = (error.response?.data ?? {}) as Record<string, unknown>
    const detail = (payload['detail'] ?? {}) as Record<string, unknown>
    const err = (payload['error'] ?? {}) as Record<string, unknown>
    return (
      (typeof detail['reason'] === 'string' ? (detail['reason'] as string) : undefined) ||
      (typeof detail['message'] === 'string' ? (detail['message'] as string) : undefined) ||
      (typeof err['message'] === 'string' ? (err['message'] as string) : undefined) ||
      error.message
    )
  }
  if (error instanceof Error) return error.message
  return '请求失败'
}
