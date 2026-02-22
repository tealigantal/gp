import React, { useEffect, useMemo, useState } from 'react'
import { Card, Steps } from 'antd'
import { syncManager } from '../../sync/SyncManager'

export default function StatusPanel({ conversationId }: { conversationId?: string | null }) {
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const unsub = syncManager.subscribe(() => setTick((v) => v + 1))
    return () => unsub()
  }, [])

  const latestRun = useMemo(() => {
    if (!conversationId) return { items: [] as any[], present: false }
    const evs = syncManager.messages(conversationId)
    const sts = evs.filter((e: any) => e?.data?.kind === 'card' && e?.data?.payload?.type === 'status').map((e: any) => e?.data?.payload)
    if (!sts.length) return { items: [] as any[], present: false }
    const groups = new Map<number, any[]>()
    for (const s of sts) {
      const run = Number(s.run_id || 0) || 0
      if (!groups.has(run)) groups.set(run, [])
      groups.get(run)!.push(s)
    }
    const runs = Array.from(groups.keys()).sort((a, b) => a - b)
    const latest = groups.get(runs[runs.length - 1]) || []
    const order = ['report_started', 'planning', 'plan_complete', 'complete']
    const map = new Map<string, any>()
    let lastTs = 0
    for (const s of latest) { map.set(String(s.code), s); const ts = Number(s?.ts || 0); if (ts > lastTs) lastTs = ts }
    // visibility rule: keep visible for a short time after complete (e.g., 8s)
    const completed = map.has('complete')
    const ageMs = Date.now() - lastTs
    const fresh = ageMs <= 60_000
    const retainAfterComplete = ageMs <= 8_000
    if ((!fresh) || (completed && !retainAfterComplete)) return { items: [] as any[], present: false }
    const currentIndex = order.findIndex((c) => !map.has(c))
    const statusIdx = currentIndex === -1 ? order.length - 1 : Math.max(0, currentIndex - 1)
    const items = order.map((code, i) => ({ title: labelOf(code), status: (i <= statusIdx ? 'finish' : (i === statusIdx + 1 ? 'process' : 'wait')) as any }))
    return { items, present: true }
  }, [conversationId, tick])

  if (!conversationId || !latestRun.present) return null
  return (
    <Card size="small" title={('进度')} style={{ marginTop: 12 }}>
      <Steps direction="vertical" size="small" items={latestRun.items} />
    </Card>
  )
}

function labelOf(code: string) {
  switch (code) {
    case 'report_started': return '开始';
    case 'planning': return '生成参数与候选';
    case 'plan_complete': return '结果生成';
    case 'complete': return '完成';
    default: return code;
  }
}
