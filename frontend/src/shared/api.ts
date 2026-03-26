import axios, { AxiosError } from 'axios'
import type {
  BookResponse,
  ChatRequest,
  ChatResponse,
  HealthResponse,
  RunResponse,
  SessionResponse,
  SideResult,
} from './contracts'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 60_000,
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

export async function postChat(payload: ChatRequest) {
  const { data } = await api.post<ChatResponse>('/api/chat', payload)
  return data
}

export function readApiError(error: unknown): string {
  if (error instanceof AxiosError) {
    return (
      (error.response?.data as any)?.detail?.reason ||
      (error.response?.data as any)?.detail?.message ||
      (error.response?.data as any)?.error?.message ||
      error.message
    )
  }
  if (error instanceof Error) return error.message
  return '请求失败'
}
