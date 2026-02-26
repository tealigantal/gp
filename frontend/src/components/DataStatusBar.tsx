import React, { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Space, Tag, Tooltip } from 'antd'
import { syncManager } from '../sync/SyncManager'

export default function DataStatusBar() {
  const [tick, setTick] = useState(0)
  useEffect(() => { const u = syncManager.subscribe(() => setTick((v)=>v+1)); return () => u() }, [])

  const { meta, hasRecCard, lastRec } = useMemo(() => {
    const cid = syncManager.currentConversationId?.()
    if (!cid) return { meta: null as any, hasRecCard: false, lastRec: null as any }
    const evs = syncManager.messages(cid)
    for (let i = evs.length - 1; i >= 0; i--) {
      const e: any = evs[i]
      if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
        const rec = e?.data?.payload || null
        return { meta: rec?.meta || null, hasRecCard: true, lastRec: rec }
      }
    }
    return { meta: null as any, hasRecCard: false, lastRec: null as any }
  }, [tick])

  if (!hasRecCard) {
    return (
      <Alert type="warning" message="尚未生成推荐。试试输入：给我推荐3只低估值" banner showIcon={false} style={{ marginBottom: 8 }} />
    )
  }
  if (!meta) {
    if (import.meta?.env?.DEV) {
      // CONTRACT_BROKEN: recommendation card exists but meta missing
      // eslint-disable-next-line no-console
      console.error('[CONTRACT_BROKEN] recommendation payload without meta', lastRec)
    }
    return (
      <Alert type="error" message="契约异常：未收到 meta（说明后端未产出真实数据）" banner showIcon={false} style={{ marginBottom: 8 }} />
    )
  }
  const ds = meta.data_status || {}
  if (!ds || Object.keys(ds).length === 0) {
    return <Alert type="error" message="data_status 缺失（禁止交易）" banner showIcon={false} style={{ marginBottom: 8 }} />
  }
  const snap = ds.snapshot || {}
  const th = ds.themes || {}
  const daily = ds.daily || {}
  const degraded = meta?.debug?.degraded === true
  const strict = meta?.strict_output === true
  const debugJson = JSON.stringify(meta?.debug || meta?.data_status || {}, null, 2)

  return (
    <div style={{ padding: '6px 8px', background: '#fafafa', border: '1px solid #eee', borderRadius: 4, marginBottom: 8 }}>
      <Space wrap size={[6, 6]}>
        <Tag color="default">as_of {meta.as_of || 'N/A'}</Tag>
        <Tag color="default">tz {meta.timezone || 'N/A'}</Tag>
        <Tag color={snap.ok ? 'green' : 'red'}>snapshot {String(snap.ok)}</Tag>
        {snap.source && <Tag color="default">src {String(snap.source)}</Tag>}
        {typeof snap.rows === 'number' && <Tag color="default">rows {snap.rows}</Tag>}
        {snap.cache && <Tag color="default">cache {String(snap.cache)}</Tag>}
        {snap.as_of_ts && <Tag color="default">as_of_ts {String(snap.as_of_ts)}</Tag>}
        {snap.error && (
          <Tooltip title={String(snap.error)}>
            <Tag color="red">{String(snap.error).slice(0, 48)}</Tag>
          </Tooltip>
        )}
        <Tag color={th.ok ? 'green' : 'red'}>themes {String(th.ok)}</Tag>
        {th.source && <Tag color="default">{String(th.source)}</Tag>}
        {Array.isArray(th.attempted) && th.attempted.length > 0 && <Tag color="default">attempted {th.attempted.join(',')}</Tag>}
        {th.as_of_ts && <Tag color="default">as_of_ts {String(th.as_of_ts)}</Tag>}
        {th.error && (
          <Tooltip title={String(th.error)}>
            <Tag color="red">{String(th.error).slice(0, 48)}</Tag>
          </Tooltip>
        )}
        <Tag color={daily.ok ? 'green' : 'red'}>daily {String(daily.ok)}</Tag>
        {typeof daily.symbols_ok === 'number' && <Tag>ok {String(daily.symbols_ok)}</Tag>}
        {typeof daily.symbols_fail === 'number' && <Tag>fail {String(daily.symbols_fail)}</Tag>}
        {daily.error_summary && (
          <Tooltip title={String(daily.error_summary)}>
            <Tag color="red">{String(daily.error_summary).slice(0, 48)}</Tag>
          </Tooltip>
        )}
        <Tag color={strict ? 'blue' : 'default'}>STRICT {strict ? 'ON' : 'OFF'}</Tag>
        {degraded && <Tag color="red">DEGRADED</Tag>}
        <Tooltip title={<pre style={{ maxWidth: 320, whiteSpace: 'pre-wrap' }}>{debugJson}</pre>}>
          <Button size="small" onClick={() => { try { navigator.clipboard?.writeText?.(debugJson) } catch {} }}>复制调试信息</Button>
        </Tooltip>
      </Space>
    </div>
  )
}
