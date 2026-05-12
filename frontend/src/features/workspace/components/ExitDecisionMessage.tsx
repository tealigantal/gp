import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { ExitDecisionArtifact } from '../../../shared/contracts'

interface ExitDecisionMessageProps {
  view: ExitDecisionArtifact
  text: string
}

function actionLabel(action: ExitDecisionArtifact['action']) {
  const mapping = {
    HOLD: { color: 'blue', label: '继续持有' },
    REDUCE: { color: 'volcano', label: '减仓暂不入场' },
    SELL: { color: 'red', label: '卖出离场' },
    WATCH: { color: 'default', label: '继续跟踪' },
  }
  return mapping[action]
}

export function ExitDecisionMessage({ view, text }: ExitDecisionMessageProps) {
  const action = actionLabel(view.action)

  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color={action.color}>{action.label}</Tag>
          <Tag>{view.symbol}</Tag>
          {view.current_state ? <Tag>{view.current_state}</Tag> : null}
        </Space>

        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>

        <Descriptions size="small" column={2}>
          <Descriptions.Item label="触发条件">{view.trigger}</Descriptions.Item>
          <Descriptions.Item label="置信度">
            {typeof view.confidence === 'number' ? `${Math.round(view.confidence * 100)}%` : '--'}
          </Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">
            {view.stop != null ? view.stop.toFixed(2) : view.invalidation || '待确认'}
          </Descriptions.Item>
          <Descriptions.Item label="止盈">
            {Array.isArray(view.take_profit) && view.take_profit.length > 0
              ? view.take_profit.map((item) => item.toFixed(2)).join(' / ')
              : '待确认'}
          </Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
