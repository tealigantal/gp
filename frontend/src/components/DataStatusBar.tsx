import React, { useEffect, useMemo, useState } from 'react'
import { Button, Modal, Space, Tag } from 'antd'
import { syncManager } from '../sync/SyncManager'

export default function DataStatusBar() {
  const [tick, setTick] = useState(0)
  const [open, setOpen] = useState(false)
  useEffect(() => { const u = syncManager.subscribe(() => setTick((v)=>v+1)); return () => u() }, [])

  const { meta, hasRecCard } = useMemo(() => {
    const cid = syncManager.currentConversationId?.()
    if (!cid) return { meta: null as any, hasRecCard: false }
    const evs = syncManager.messages(cid)
    for (let i = evs.length - 1; i >= 0; i--) {
      const e: any = evs[i]
      if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
        const rec = e?.data?.payload || null
        return { meta: rec?.meta || null, hasRecCard: true }
      }
    }
    return { meta: null as any, hasRecCard: false }
  }, [tick])

  if (!hasRecCard || !meta) return null
  const ds = meta.data_status || {}
  const snap = ds.snapshot || {}
  const th = ds.themes || {}
  const daily = ds.daily || {}
  const ml = ds.mainline || {}
  const degraded = meta?.debug?.degraded === true
  const strict = meta?.strict_output === true
  const debugJson = JSON.stringify({ debug: meta?.debug || {}, data_status: ds }, null, 2)

  return (
    <div style={{ padding: '6px 8px', background: '#fafafa', border: '1px solid #eee', borderRadius: 4, marginBottom: 8 }}>
      <Space wrap size={[8, 8]}>
        <Tag color={strict ? 'blue' : 'default'}>STRICT {strict ? 'ON' : 'OFF'}</Tag>
        <Tag color={snap.ok ? 'green' : 'red'}>Snapshot {snap.ok ? 'OK' : 'FAIL'}</Tag>
        <Tag color={th.ok ? 'green' : 'red'}>Themes {th.ok ? 'OK' : 'FAIL'}</Tag>
        <Tag color={ml.ok ? 'green' : 'default'}>Mainline {ml.ok ? 'OK' : 'N/A'}</Tag>
        <Tag color={daily.ok ? 'green' : 'red'}>Daily ok {String(daily.symbols_ok || 0)}/fail {String(daily.symbols_fail || 0)}</Tag>
        {degraded && <Tag color="red">DEGRADED</Tag>}
        <Button size="small" onClick={() => setOpen(true)}>Details / Copy debug</Button>
      </Space>
      <Modal title="数据状态详情" open={open} onCancel={() => setOpen(false)} onOk={() => setOpen(false)} okText="关闭" cancelButtonProps={{ style: { display: 'none' } }}>
        <div style={{ marginBottom: 8 }}>
          <Button size="small" onClick={() => { try { navigator.clipboard?.writeText?.(debugJson) } catch {} }}>复制调试 JSON</Button>
        </div>
        <pre style={{ maxHeight: 320, overflow: 'auto' }}>{debugJson}</pre>
      </Modal>
    </div>
  )
}

