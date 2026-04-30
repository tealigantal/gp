import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { LiveEntryDecision } from '../../../shared/contracts'
import { fmtPct } from '../../../shared/format'
import { executionStateMeta } from '../presentation'

interface LiveCheckMessageCardProps {
  view: LiveEntryDecision
  text: string
}

export function LiveCheckMessageCard({ view, text }: LiveCheckMessageCardProps) {
  const state = executionStateMeta(view.execution_state)

  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color={state.color}>{state.label}</Tag>
          <Tag>{view.symbol}</Tag>
          {view.gate_state ? <Tag>{view.gate_state}</Tag> : null}
        </Space>

        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>

        <Descriptions size="small" column={2}>
          <Descriptions.Item label="买入区">{view.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{view.stop_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{view.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="下一步">{view.next_action}</Descriptions.Item>
          <Descriptions.Item label="VWAP">{view.vwap?.toFixed(2) || '--'}</Descriptions.Item>
          <Descriptions.Item label="ORB30">
            {view.orb30_low != null && view.orb30_high != null
              ? `${view.orb30_low.toFixed(2)} - ${view.orb30_high.toFixed(2)}`
              : '--'}
          </Descriptions.Item>
          <Descriptions.Item label="距买点">{fmtPct(view.entry_distance_pct, 2)}</Descriptions.Item>
          <Descriptions.Item label="相对量能">{view.slot_rel_vol?.toFixed(2) || '--'}x</Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
