import type {
  ChatResponse,
  ConversationDetail,
  ConversationSession,
  HealthStatus,
  RecommendationPublication,
} from './contracts'

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string; error?: string } | null
    throw new ApiError(response.status, body?.detail || body?.error || `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const getHealth = () => request<HealthStatus>('/api/health')
export const getPublication = () => request<RecommendationPublication>('/api/recommendation/current')
export const getConversations = () => request<ConversationSession[]>('/api/conversations?limit=30')
export const getConversation = (sessionId: string) => request<ConversationDetail>(`/api/conversations/${encodeURIComponent(sessionId)}`)
export async function deleteConversation(sessionId: string): Promise<void> {
  try {
    await request<void>(`/api/conversations/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
  } catch (error) {
    if (error instanceof ApiError && error.status === 404 && error.message === 'conversation_not_found') return
    throw error
  }
}
export const sendChat = (message: string, clientTurnId: string, sessionId?: string) =>
  request<ChatResponse>('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message, client_turn_id: clientTurnId, ...(sessionId ? { session_id: sessionId } : {}) }),
  })

export function friendlyError(error: unknown): string {
  if (!(error instanceof ApiError)) return '暂时无法连接服务，请稍后重试。'
  if (error.status === 404 && error.message === 'publication_not_found') return '当前还没有可用推荐。系统会在证据准备完整后发布结果。'
  if (error.status === 503 && error.message.startsWith('narration_unavailable')) return '自然语言助手暂时不可用，本次回答没有保存。请稍后重试。'
  if (error.status === 409 && error.message === 'conversation_deleted') return '这条对话已被删除，请新建对话后继续。'
  if (error.status === 409) return '当前推荐版本已变化，请同步最新状态后再提问。'
  return `请求未完成：${error.message}`
}
