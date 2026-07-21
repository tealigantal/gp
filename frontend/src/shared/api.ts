import axios, { AxiosError } from 'axios'
import type {
  BookResponse,
  ChatRequest,
  ChatResponse,
  HealthResponse,
  LunchResponse,
  OpsRunResponse,
  RunResponse,
  SessionDiagnosticsResponse,
  SessionListItem,
  SessionResponse,
  SideResult,
} from './contracts'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 0,
})

export async function getHealth() {
  const { data } = await api.get<HealthResponse>('/api/health')
  return data
}

export async function getCurrentBook() {
  const { data } = await api.get<BookResponse>('/api/book/current')
  return data
}

export async function getCurrentLunch() {
  const { data } = await api.get<LunchResponse>('/api/lunch/current')
  return data
}

export async function getSession(sessionId: string) {
  const { data } = await api.get<SessionResponse>(`/api/session/${encodeURIComponent(sessionId)}`)
  return data
}

export async function getSessionDiagnostics(sessionId: string) {
  const { data } = await api.get<SessionDiagnosticsResponse>(`/api/session/${encodeURIComponent(sessionId)}/diagnostics`)
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
  const { data } = await api.post<ChatResponse>('/api/chat', payload)
  return data
}

export async function runOpsTool(operation: string) {
  const { data } = await api.post<OpsRunResponse>(`/api/ops/repair/${encodeURIComponent(String(operation || ''))}`)
  return data
}

export function readApiError(error: unknown): string {
  if (error instanceof AxiosError) {
    if (error.code === AxiosError.ECONNABORTED) {
      return '请求超时。后端可能仍在处理中，请稍后刷新结果。'
    }
    const payload = (error.response?.data ?? {}) as Record<string, unknown>
    const detail = (payload.detail ?? {}) as Record<string, unknown>
    const err = (payload.error ?? {}) as Record<string, unknown>
    return (
      (typeof detail.reason === 'string' ? detail.reason : undefined) ||
      (typeof detail.message === 'string' ? detail.message : undefined) ||
      (typeof payload.detail === 'string' ? payload.detail : undefined) ||
      (typeof err.message === 'string' ? err.message : undefined) ||
      error.message
    )
  }
  if (error instanceof Error) return error.message
  return '请求失败'
}
