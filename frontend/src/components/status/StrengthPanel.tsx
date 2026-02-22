import React, { useEffect, useMemo, useState } from 'react'
import { Card, List, Tag } from 'antd'
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

  if (!conversationId) return null
  return (
    <Card size="small" title="主题热度" style={{ marginTop: 12 }}>
      {themes.length === 0 ? <span style={{ color: '#999' }}>暂无数据（生成一次推荐后显示）</span> : (
        <List dataSource={themes.slice(0, 6)} renderItem={(t: any) => (
          <List.Item>
            <span>{t?.name || '主题'}</span>
            {t?.strength != null && <Tag color="geekblue" style={{ marginLeft: 8 }}>强度 {t.strength}</Tag>}
          </List.Item>
        )} />
      )}
    </Card>
  )
}

