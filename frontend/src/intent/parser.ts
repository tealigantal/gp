export type RecommendIntent = {
  type: 'recommend'
  topk?: number
  universe?: 'auto' | 'symbols'
  symbols?: string[]
  risk?: 'conservative' | 'normal' | 'aggressive'
}

export type KlineIntent = {
  type: 'kline'
  symbols: string[]
}

export type ThemesIntent = { type: 'themes' }
export type ProgressIntent = { type: 'progress' }
export type ChatIntent = { type: 'chat' }

export type ParsedIntent = RecommendIntent | KlineIntent | ThemesIntent | ProgressIntent | ChatIntent

import { resolveSymbolsFromText } from './symbols'

const DIGIT_CODE = /\b\d{6}\b/g

function extractCodes(text: string): string[] {
  const m = text.match(DIGIT_CODE)
  return Array.from(new Set(m || []))
}

function extractTopk(text: string): number | undefined {
  // e.g. "3只", "3个", or plain number "3"
  const m = text.match(/(\d{1,2})\s*(?:只|个)?/)
  if (!m) return undefined
  const n = Number(m[1])
  if (!Number.isFinite(n)) return undefined
  if (n <= 0) return undefined
  return Math.min(Math.max(n, 1), 10)
}

function extractRisk(text: string): 'conservative' | 'normal' | 'aggressive' | undefined {
  if (/保守/.test(text)) return 'conservative'
  if (/(中性|正常)/.test(text)) return 'normal'
  if (/(积极|激进)/.test(text)) return 'aggressive'
  return undefined
}

export function parseIntent(text: string): ParsedIntent {
  const t = text.trim()
  if (!t) return { type: 'chat' }

  // progress / refresh
  if (/(进度|刷新进度)/.test(t)) {
    return { type: 'progress' }
  }

  // themes hotness
  if (/(主题|热点|热度)/.test(t) && /(今天|现在|如何|怎样|怎么样)?/.test(t)) {
    return { type: 'themes' }
  }

  // kline request
  if (/(K线|k线|k线图|K 线|看看.*K线|K线看看)/.test(t) || /看看\d{6}/.test(t)) {
    const symbols = resolveSymbolsFromText(t)
    if (symbols.length) return { type: 'kline', symbols }
    // fallback: if contains only kline but no code, treat as chat to avoid dead end
    return { type: 'chat' }
  }

  // recommend request（包含同义词：荐股/选股/建议）
  if (/(荐股|选股|推荐|建议|来|给我).*?(只|个)?/.test(t)) {
    const topk = extractTopk(t)
    const risk = extractRisk(t)
    const symbols = resolveSymbolsFromText(t)
    const hasSymbols = symbols.length > 0 || /(自选|只看|这些|这几个)/.test(t)
    const universe: 'auto' | 'symbols' = hasSymbols ? 'symbols' : 'auto'
    return { type: 'recommend', topk, universe, symbols, risk }
  }

  return { type: 'chat' }
}
