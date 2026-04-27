import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { LiveEntryDecision } from '../../../shared/contracts'

interface LiveCheckMessageCardProps {
  view: LiveEntryDecision
  text: string
}

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return `${(value * 100).toFixed(2)}%`
}

export function LiveCheckMessageCard({ view, text }: LiveCheckMessageCardProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color={view.can_execute_now ? 'green' : 'blue'}>{view.execution_state}</Tag>
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
            {view.orb30_low != null && view.orb30_high != null ? `${view.orb30_low.toFixed(2)} - ${view.orb30_high.toFixed(2)}` : '--'}
          </Descriptions.Item>
          <Descriptions.Item label="距买点">{pct(view.entry_distance_pct)}</Descriptions.Item>
          <Descriptions.Item label="相对量能">{view.slot_rel_vol?.toFixed(2) || '--'}x</Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
