import type { ConversationSummary, ThreadItem, RecommendationArtifact, SearchHit } from './contracts'

// Narrow unknown server payloads into frozen contracts without inventing new truth.

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function asString(v: unknown, d = ''): string {
  return typeof v === 'string' ? v : d
}

function asNumber(v: unknown, d = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : d
}

function arrOf<T>(v: unknown, map: (x: unknown) => T): T[] {
  return Array.isArray(v) ? v.map(map) : []
}

export function asConversationSummary(x: unknown): ConversationSummary {
  const o = isRecord(x) ? x : {}
  return {
    id: asString(o.id, ''),
    title: asString(o.title, asString(o.id, '')),
    last_seq: asNumber(o.last_seq, 0),
    last_item_preview: asString(o.last_item_preview, ''),
    last_item_kind: (typeof o.last_item_kind === 'string' && (['text','recommendation','status'] as readonly string[]).includes(o.last_item_kind))
      ? (o.last_item_kind as 'text'|'recommendation'|'status')
      : 'text',
    last_item_ts: o.last_item_ts != null ? String(o.last_item_ts) : null,
    unread_count: asNumber(o.unread_count, 0),
    updated_at: o.updated_at != null ? String(o.updated_at) : null,
  }
}

export function asThreadItem(x: unknown): ThreadItem | null {
  const o = isRecord(x) ? x : null
  if (!o) return null
  const base = {
    id: asString(o.id, ''),
    conversation_id: asString(o.conversation_id, ''),
    seq: asNumber(o.seq, 0),
    created_at: asString(o.created_at, ''),
    role: (typeof o.role === 'string' && (['user','assistant','system'] as readonly string[]).includes(o.role)) ? (o.role as 'user'|'assistant'|'system') : 'user',
  }
  switch (o.kind) {
    case 'text':
      return { ...base, kind: 'text', content: asString(o.content, '') }
    case 'recommendation':
      return {
        ...base,
        kind: 'recommendation',
        artifact_id: asString(o.artifact_id, base.id),
        summary: isRecord(o.summary)
          ? { total: asNumber(o.summary.total, 0), top_symbols: arrOf(o.summary.top_symbols, (s) => asString(s)) }
          : undefined,
      }
    case 'status':
      return { ...base, kind: 'status', code: o.code != null ? String(o.code) : undefined, message: o.message != null ? String(o.message) : undefined }
    default:
      return null
  }
}

export function asRecommendationArtifact(x: unknown): RecommendationArtifact {
  const o = isRecord(x) ? x : {}
  const picksIn = Array.isArray(o.picks) ? (o.picks as unknown[]) : []
  const picksOut = picksIn.map((p) => {
    const pr = isRecord(p) ? p : {}
    type PickOut = RecommendationArtifact['picks'][number]
    const item: PickOut = { symbol: asString(pr.symbol, '') }
    if (pr.name) item.name = asString(pr.name)
    if (pr.theme) item.theme = asString(pr.theme)
    if (isRecord(pr.champion)) {
      const score = typeof pr.champion.score === 'number' ? pr.champion.score : undefined
      item.champion = { strategy: asString(pr.champion.strategy, ''), score }
    }
    if (isRecord(pr.trade_plan)) {
      const tp = pr.trade_plan as Record<string, unknown>
      const bands = isRecord(tp.bands) ? tp.bands as Record<string, unknown> : {}
      const actions = isRecord(tp.actions) ? tp.actions as Record<string, unknown> : {}
      const risk = isRecord(tp.risk) ? tp.risk as Record<string, unknown> : {}
      const b = {
        S1: typeof bands.S1 === 'number' ? bands.S1 : undefined,
        S2: typeof bands.S2 === 'number' ? bands.S2 : undefined,
        R1: typeof bands.R1 === 'number' ? bands.R1 : undefined,
        R2: typeof bands.R2 === 'number' ? bands.R2 : undefined,
      }
      const a = {
        window_A: typeof actions.window_A === 'string' ? actions.window_A : undefined,
        window_B: typeof actions.window_B === 'string' ? actions.window_B : undefined,
      }
      const r = {
        stop_loss: typeof risk.stop_loss === 'string' ? risk.stop_loss : undefined,
        time_stop: typeof risk.time_stop === 'string' ? risk.time_stop : undefined,
        no_averaging_down: typeof risk.no_averaging_down === 'boolean' ? risk.no_averaging_down : undefined,
      }
      const entry = Array.isArray(tp.entry) ? (tp.entry as unknown[]).map((v) => String(v)) : (typeof tp.entry === 'string' ? String(tp.entry) : undefined)
      const take = Array.isArray(tp.take) ? (tp.take as unknown[]).map((v) => String(v)) : (typeof tp.take === 'string' ? String(tp.take) : undefined)
      const stop = typeof tp.stop === 'string' ? String(tp.stop) : undefined
      item.trade_plan = { entry, take, stop, bands: b, actions: a, risk: r }
    }
    if (isRecord(pr.chip)) {
      item.chip = { model_used: pr.chip.model_used as string | undefined }
    }
    return item
  })
  const diagnostics = isRecord(o.diagnostics) ? (o.diagnostics as Record<string, unknown>) : undefined
  const meta = isRecord(o.meta) ? (o.meta as Record<string, unknown>) : undefined
  return {
    id: asString(o.id, ''),
    as_of: o.as_of != null ? String(o.as_of) : null,
    timezone: asString(o.timezone, 'Asia/Shanghai'),
    picks: picksOut,
    tradeable: typeof o.tradeable === 'boolean' ? (o.tradeable as boolean) : undefined,
    disclaimer: o.disclaimer != null ? String(o.disclaimer) : null,
    message: o.message != null ? String(o.message) : null,
    meta: meta ? { env_grade: typeof meta.env_grade === 'string' ? (meta.env_grade as string) : undefined } : undefined,
    diagnostics: diagnostics
      ? {
          degraded: !!diagnostics.degraded,
          degrade_reasons: Array.isArray(diagnostics.degrade_reasons)
            ? (diagnostics.degrade_reasons as unknown[]).map((r) => {
                if (isRecord(r)) {
                  return { reason_code: asString(r.reason_code, 'UNKNOWN'), detail: r.detail }
                }
                return { reason_code: 'UNKNOWN' }
              })
            : [],
        }
      : undefined,
  }
}

export function asSearchHit(x: unknown): SearchHit {
  const o = isRecord(x) ? x : {}
  return {
    conversation_id: asString(o.conversation_id, ''),
    seq: asNumber(o.seq, 0),
    message_id: asString(o.message_id, ''),
    preview: asString(o.preview, ''),
    highlights: Array.isArray(o.highlights)
      ? (o.highlights as unknown[]).map((h) => {
          const hr = isRecord(h) ? h : {}
          return { start: asNumber(hr.start, 0), length: asNumber(hr.length, 0) }
        })
      : undefined,
    anchor: {
      conversation_id: isRecord(o.anchor) ? asString(o.anchor.conversation_id, asString(o.conversation_id, '')) : asString(o.conversation_id, ''),
      seq: isRecord(o.anchor) ? asNumber(o.anchor.seq, asNumber(o.seq, 0)) : asNumber(o.seq, 0),
    },
  }
}

export function asSearchHits(arr: unknown): SearchHit[] {
  if (!Array.isArray(arr)) return []
  return arr.map(asSearchHit)
}
