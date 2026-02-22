import React, { useEffect, useState } from 'react'
import { Card, Input, Button, Space, message, Segmented, Typography } from 'antd'
import DockPanel from './DockPanel'
import { syncManager } from '../sync/SyncManager'
import StatusPanel from './status/StatusPanel'
import StrengthPanel from './status/StrengthPanel'
import { getRiskProfile, setRiskProfile } from '../store/settings'

export default function ToolsPanel({
  conversationId,
  onEnsureConversation,
  onRefresh
}: {
  conversationId?: string | null
  onEnsureConversation: (cid: string) => void
  onRefresh: () => void
}) {
  const [symbol, setSymbol] = useState('')
  const [open, setOpen] = useState(false)
  const [dockSymbol, setDockSymbol] = useState<string | null>(null)
  const [risk, setRisk] = useState(getRiskProfile())

  useEffect(() => { setRisk(getRiskProfile()) }, [])

  async function showKline(sym?: string) {
    try {
      const s = (sym || symbol || '').trim()
      if (!s) return
      const cid = conversationId || ('sess-' + Date.now())
      if (!conversationId) onEnsureConversation(cid)
      // 事件化：追加K线卡
      syncManager.pushOutbox({
        conversation_id: cid,
        type: 'message.created',
        actor_id: 'assistant',
        data: { message_id: 'card-kline-' + Date.now(), kind: 'card', content: 'kline', payload: { type: 'kline', symbol: s } }
      })
      await syncManager.flush()
      setDockSymbol(s)
      setOpen(true)
      onRefresh()
    } catch (e: any) {
      message.error(e?.message || '显示失败')
    }
  }

  return (
    <div>
      <Card size="small" title="快速K线" style={{ marginBottom: 12 }}>
        <Space.Compact style={{ width: '100%' }}>
          <Input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="输入代码后回车" onPressEnter={() => showKline()} />
          <Button type="primary" onClick={() => showKline()}>查看</Button>
        </Space.Compact>
      </Card>
      <Card size="small" title="风险偏好" style={{ marginBottom: 12 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Segmented
            value={risk}
            onChange={(v) => { const nv = v as any; setRisk(nv); setRiskProfile(nv) }}
            options={[
              { label: '保守', value: 'conservative' },
              { label: '中性', value: 'normal' },
              { label: '积极', value: 'aggressive' }
            ]}
          />
          <Typography.Text type="secondary">若文本未指明风险，默认使用此设置。</Typography.Text>
        </Space>
      </Card>
      <DockPanel open={open} symbol={dockSymbol} onClose={() => setOpen(false)} />
      <StatusPanel conversationId={conversationId} />
      <StrengthPanel conversationId={conversationId} />
    </div>
  )
}




