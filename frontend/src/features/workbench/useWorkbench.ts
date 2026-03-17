import { useEffect, useMemo, useState } from 'react'
import type { WorkbenchSnapshot, OrderIntent, RecommendV2 } from '../../api/types'
import { getWorkbench, postOperatorIntentAction } from '../../api/client'

export type RecItemVM = {
  symbol: string
  name?: string
  status: 'allow' | 'degraded' | 'blocked'
  reasons: string[]
  final_score?: number
  confidence?: number
  reliability?: number
  actionable?: boolean
}

export type WorkbenchVM = {
  as_of?: string | null
  recs: RecItemVM[]
  run_status?: 'allow' | 'degraded' | 'blocked'
  intentsPreview: OrderIntent[]
  portfolioSummary: { positions: number; pending: number; events: number }
  validationSummary: { healthy: number; degraded: number; killed: number; wf_missing: number; live_shadow_ok: boolean }
  raw: WorkbenchSnapshot
}

export function useWorkbench(params: { run_id?: string; as_of?: string; event_limit?: number } = {}) {
  const [data, setData] = useState<WorkbenchSnapshot | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true); setError(null)
    try {
      const snap = await getWorkbench(params)
      setData(snap)
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [params.run_id, params.as_of])

  const vm: WorkbenchVM | null = useMemo(() => {
    if (!data) return null
    const rec = (data.recommend || {}) as RecommendV2
    const items = Array.isArray(rec?.items) ? rec.items : []
    const recs: RecItemVM[] = items.map((it: any) => {
      const gd = (it?.gating_decision || {})
      const status = (gd?.decision || 'allow') as 'allow'|'degraded'|'blocked'
      const reasons = Array.isArray(gd?.reasons) ? gd.reasons.slice(0, 4) : []
      return {
        symbol: String(it?.symbol || ''),
        name: it?.name,
        status,
        reasons,
        final_score: typeof it?.final_score === 'number' ? it.final_score : undefined,
        confidence: typeof it?.confidence === 'number' ? it.confidence : undefined,
        reliability: typeof it?.reliability_score === 'number' ? it.reliability_score : undefined,
        actionable: !!it?.actionable,
      }
    })
    // validation summary aggregation
    const parts: any = (data.validation_summary || {}).parts || {}
    const health: any = parts.strategy_health || {}
    let healthy=0, degraded=0, killed=0
    Object.values(health).forEach((v: any) => {
      const s = (v as any)?.status
      if (s==='healthy') healthy++
      else if (s==='degraded') degraded++
      else if (s==='killed') killed++
    })
    const wf: any = parts.walkforward || {}
    let wf_missing=0
    Object.values(wf).forEach((v: any) => { if (!v || v.available===false) wf_missing++ })
    const live_ok = !!(data.live_shadow_summary && data.live_shadow_summary.available)
    const portfolioSummary = {
      positions: Array.isArray((data.portfolio as any)?.positions) ? (data.portfolio as any).positions.length : 0,
      pending: Array.isArray((data.portfolio as any)?.pending_intents) ? (data.portfolio as any).pending_intents.length : 0,
      events: Array.isArray((data.portfolio as any)?.recent_events) ? (data.portfolio as any).recent_events.length : 0,
    }
    return {
      as_of: data.as_of,
      recs,
      run_status: (rec as any)?.run_gating?.decision,
      intentsPreview: Array.isArray(data.intents_preview) ? data.intents_preview : [],
      portfolioSummary,
      validationSummary: { healthy, degraded, killed, wf_missing, live_shadow_ok: live_ok },
      raw: data,
    }
  }, [data])

  async function admit(run_id?: string, as_of?: string, symbol?: string) {
    await postOperatorIntentAction({ action: 'admit', run_id, as_of, symbol })
    await refresh()
  }
  async function reject(run_id?: string, as_of?: string, symbol?: string) {
    await postOperatorIntentAction({ action: 'reject', run_id, as_of, symbol })
    await refresh()
  }
  async function cancel(intent_id: string) {
    await postOperatorIntentAction({ action: 'cancel', intent_id })
    await refresh()
  }

  return { loading, error, vm, refresh, admit, reject, cancel }
}

