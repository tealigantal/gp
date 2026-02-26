import React, { useEffect, useMemo, useState } from 'react'
import { Card, List, Tag, Tooltip } from 'antd'
import { syncManager } from '../../sync/SyncManager'

export default function StrengthPanel({ conversationId }: { conversationId?: string | null }) {
  const [tick, setTick] = useState(0)
  useEffect(() => { const u = syncManager.subscribe(() => setTick((v)=>v+1)); return () => u() }, [])

  const themes = useMemo(() => {
    if (!conversationId) return [] as any[]
    const evs = syncManager.messages(conversationId)
    for (let i = evs.length - 1; i >= 0; i--) {
      const e: any = evs[i]
      if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
        const th = e?.data?.payload?.meta?.themes
        if (Array.isArray(th)) return th
      }
    }
    return [] as any[]
  }, [conversationId, tick])
  const { hints, hasRecCard } = useMemo(() => {
    if (!conversationId) return [] as any[]
    const evs = syncManager.messages(conversationId)
    for (let i = evs.length - 1; i >= 0; i--) {
      const e: any = evs[i]
      if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
        const mh = e?.data?.payload?.meta?.mover_hints
        if (Array.isArray(mh)) {
          const arr = [...mh]
          arr.sort((a: any, b: any) => (Number.isFinite(b?.chg_num) ? b.chg_num : -Infinity) - (Number.isFinite(a?.chg_num) ? a.chg_num : -Infinity))
          return { hints: arr, hasRecCard: true }
        }
        return { hints: [] as any[], hasRecCard: true }
      }
    }
    return { hints: [] as any[], hasRecCard: false }
  }, [conversationId, tick])

  if (!conversationId) return null
  return (
    <Card size="small" title="主题与强势线索" style={{ marginTop: 12 }}>
      {themes.length === 0 ? <span style={{ color: '#999' }}>暂无数据（生成一次推荐后显示）</span> : (
        <List dataSource={themes.slice(0, 6)} renderItem={(t: any) => (
          <List.Item>
            <span>{t?.name || '主题'}</span>
            {t?.strength ? <Tag color="geekblue" style={{ marginLeft: 8 }}>强度 {t.strength}</Tag> : <Tag color="default" style={{ marginLeft: 8 }}>N/A</Tag>}
            {t?.source && <Tag color="default" style={{ marginLeft: 8 }}>{t.source}</Tag>}
          </List.Item>
        )} />
      )}
      <div style={{ marginTop: 8 }}>
        <div style={{ color: '#999', marginBottom: 4 }}>强势线索（来自快照）</div>
        {!hasRecCard ? (
          <span style={{ color: '#999' }}>暂无数据（生成一次推荐后显示）</span>
        ) : hints.length === 0 ? (
          <span style={{ color: '#bbb' }}>N/A</span>
        ) : (
          <List dataSource={hints.slice(0, 6)} renderItem={(h: any) => (
            <List.Item>
              <span>{h?.symbol || '-'}</span>
              {h?.chg ? <Tag color="green" style={{ marginLeft: 8 }}>{h.chg}</Tag> : <Tag style={{ marginLeft: 8 }}>N/A</Tag>}
              {h?.source && <Tag style={{ marginLeft: 8 }}>{h.source}</Tag>}
              {Array.isArray(h?.evidence) && h.evidence.length > 0 && (
                <Tooltip title={h.evidence.join(', ')}><Tag style={{ marginLeft: 8 }}>evidence</Tag></Tooltip>
              )}
            </List.Item>
          )} />
        )}
      </div>
    </Card>
  )
}
