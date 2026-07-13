import axios, { AxiosError } from 'axios'
import type {
  ChatRequest,
  ChatResponse,
  ChatHistoryResponse,
  HealthResponse,
} from './contracts'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 0,
})

export async function getHealth() {
  const { data } = await api.get<HealthResponse>('/api/health')
  return data
}

export async function getSession(sessionId: string) {
  const { data } = await api.get<ChatHistoryResponse>(`/api/chat/${encodeURIComponent(sessionId)}`)
  return data
}

export async function postChat(payload: ChatRequest) {
  const { data } = await api.post<ChatResponse>('/api/chat', payload)
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
