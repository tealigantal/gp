import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { ExitDecisionArtifact } from '../../../shared/contracts'

interface ExitDecisionMessageProps {
  view: ExitDecisionArtifact
  text: string
}

export function ExitDecisionMessage({ view, text }: ExitDecisionMessageProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color={view.action === 'SELL' ? 'red' : view.action === 'REDUCE' ? 'volcano' : 'blue'}>{view.action}</Tag>
          <Tag>{view.symbol}</Tag>
          {view.current_state ? <Tag>{view.current_state}</Tag> : null}
        </Space>
        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="触发条件">{view.trigger}</Descriptions.Item>
          <Descriptions.Item label="置信度">{typeof view.confidence === 'number' ? `${Math.round(view.confidence * 100)}%` : '--'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">
            {view.stop != null ? view.stop.toFixed(2) : view.invalidation || '待确认'}
          </Descriptions.Item>
          <Descriptions.Item label="止盈">
            {Array.isArray(view.take_profit) && view.take_profit.length > 0 ? view.take_profit.map((item) => item.toFixed(2)).join(' / ') : '待确认'}
          </Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
