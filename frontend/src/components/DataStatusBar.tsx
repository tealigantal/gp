import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Space, Tag, Tooltip } from 'antd'
import { syncManager } from '../sync/SyncManager'

export default function DataStatusBar() {
  const [tick, setTick] = useState(0)
  useEffect(() => { const u = syncManager.subscribe(() => setTick((v)=>v+1)); return () => u() }, [])

  const meta = useMemo(() => {
    const cid = syncManager.currentConversationId?.()
    if (!cid) return null
    const evs = syncManager.messages(cid)
    for (let i = evs.length - 1; i >= 0; i--) {
      const e: any = evs[i]
      if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
        return e?.data?.payload?.meta || null
      }
    }
    return null
  }, [tick])

  if (!meta) return (
    <Alert type="warning" message="未收到 meta（契约异常）" banner showIcon={false} style={{ marginBottom: 8 }} />
  )
  const ds = meta.data_status || {}
  const snap = ds.snapshot || {}
  const th = ds.themes || {}
  const degraded = meta?.debug?.degraded === true

  return (
    <div style={{ padding: '6px 8px', background: '#fafafa', border: '1px solid #eee', borderRadius: 4, marginBottom: 8 }}>
      <Space wrap>
        <Tag color="default">as_of {meta.as_of || 'N/A'}</Tag>
        <Tag color="default">tz {meta.timezone || 'N/A'}</Tag>
        <Tag color={snap.ok ? 'green' : 'red'}>snapshot {String(snap.ok)}</Tag>
        {snap.source && <Tag color="default">src {String(snap.source)}</Tag>}
        {typeof snap.rows === 'number' && <Tag color="default">rows {snap.rows}</Tag>}
        {snap.cache && <Tag color="default">cache {String(snap.cache)}</Tag>}
        {snap.error && <Tag color="red">{String(snap.error).slice(0, 48)}</Tag>}
        <Tag color={th.ok ? 'green' : 'red'}>themes {String(th.ok)}</Tag>
        {th.source && <Tag color="default">{String(th.source)}</Tag>}
        {Array.isArray(th.attempted) && th.attempted.length > 0 && <Tag color="default">attempted {th.attempted.join(',')}</Tag>}
        {th.error && <Tag color="red">{String(th.error).slice(0, 48)}</Tag>}
        {degraded && <Tag color="red">DEGRADED</Tag>}
      </Space>
    </div>
  )
}

