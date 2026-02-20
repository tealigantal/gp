import axios from 'axios'
import type { ChatReq, ChatResp, RecommendReq, RecommendResp, HealthResp, OHLCVResp } from './types'

const baseURL = import.meta.env.VITE_API_BASE || '/api'

export const api = axios.create({ baseURL })

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

