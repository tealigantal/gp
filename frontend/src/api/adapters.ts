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
  const diagnostics = isRecord(o.diagnostics) ? (o.diagnostics as Record<string, unknown>) : undefined
  const meta = isRecord(o.meta) ? (o.meta as Record<string, unknown>) : undefined
  // V2 card: adapt v2 artifact for picks, attach v2 for decision-chain UI
  if (o.artifact_version === 'v2' && isRecord((o as any).v2)) {
    const v2 = (o as any).v2 as unknown as import('./types').RecommendV2
    const compat = adaptV2ToRecommendationArtifact(v2)
    return {
      id: asString(o.id, ''),
      artifact_version: 'v2',
      run_id: typeof (o as any).run_id === 'string' ? (o as any).run_id : (v2.run_id || null),
      source: typeof (o as any).source === 'string' ? (o as any).source : 'gated_v2',
      summary: isRecord((o as any).summary)
        ? {
            total: asNumber(((o as any).summary as any).total, 0),
            top_symbols: arrOf(((o as any).summary as any).top_symbols, (s) => String(s)),
            tradeable: typeof ((o as any).summary as any).tradeable === 'boolean' ? (((o as any).summary as any).tradeable as boolean) : undefined,
            market_regime: typeof ((o as any).summary as any).market_regime === 'string' ? String(((o as any).summary as any).market_regime) : undefined,
            reason: typeof ((o as any).summary as any).reason === 'string' ? String(((o as any).summary as any).reason) : undefined,
            run_gating: isRecord(((o as any).summary as any).run_gating)
              ? {
                  decision: String((((o as any).summary as any).run_gating as any).decision) as any,
                  reasons: arrOf((((o as any).summary as any).run_gating as any).reasons, (r) => String(r)),
                  warnings: arrOf((((o as any).summary as any).run_gating as any).warnings, (r) => String(r)),
                }
              : undefined,
          }
        : undefined,
      as_of: compat.as_of,
      timezone: compat.timezone,
      picks: compat.picks,
      tradeable: compat.tradeable,
      disclaimer: compat.disclaimer,
      message: compat.message,
      meta: compat.meta,
      v2,
    }
  }
  // Legacy card
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

// --- V2 -> existing RecommendationArtifact adapter (minimal) ---
import type { RecommendV2 } from './types'

export function adaptV2ToRecommendationArtifact(v2: RecommendV2): RecommendationArtifact {
  // Map a V2 artifact into a shape compatible with RecommendationCard
  const picks = (v2.items || []).map((it) => {
    const out: RecommendationArtifact['picks'][number] = {
      symbol: it.symbol,
      name: it.name,
      champion: it.strategy ? { strategy: String(it.strategy) } : undefined,
      trade_plan: {
        // Minimal mapping: render entry/stop/take as strings; bands unavailable in V2
        entry: it.entry_zone ? it.entry_zone.map((x) => String(x)) : undefined,
        take: Array.isArray(it.take_profit) ? it.take_profit.map((x) => String(x)) : undefined,
        stop: typeof it.stop === 'number' ? String(it.stop) : undefined,
        bands: {},
        actions: {},
        risk: { no_averaging_down: undefined },
      },
    }
    return out
  })
  return {
    id: v2.run_id || '',
    as_of: v2.as_of || null,
    timezone: 'Asia/Shanghai',
    picks,
    tradeable: v2.tradeable,
    disclaimer: null,
    message: v2.reason || null,
    meta: {},
  }
}
