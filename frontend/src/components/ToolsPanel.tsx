import React, { useEffect, useState } from 'react'
import { Card, Input, Button, Space, message, Segmented, Typography } from 'antd'
// Deprecated status widgets removed from main UI
import { getRiskProfile, setRiskProfile } from '../store/settings'
import { useSelectedArtifact } from '../features/artifacts/useSelectedArtifact'

export default function ToolsPanel(props: { conversationId?: string | null; onEnsureConversation?: (cid: string) => void; onRefresh?: () => void }) {
  const { conversationId } = props
  const [symbol, setSymbol] = useState('')
  const [risk, setRisk] = useState(getRiskProfile())
  const { openKline } = useSelectedArtifact()

  useEffect(() => { setRisk(getRiskProfile()) }, [])

  async function showKline(sym?: string) {
    try {
      const s = (sym || symbol || '').trim()
      if (!s) return
      openKline(s)
    } catch (e: unknown) {
      const err = e as { message?: string }
      message.error(err?.message || '显示失败')
    }
  }

  return (
    <div>
      <Card size="small" title="查看 K 线" style={{ marginBottom: 12 }}>
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
              { label: '均衡', value: 'normal' },
              { label: '激进', value: 'aggressive' }
            ]}
          />
          <Typography.Text type="secondary">若未指定日期，默认使用最近数据。</Typography.Text>
        </Space>
      </Card>
    </div>
  )
}

