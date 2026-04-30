import { Card, List, Space, Tag, Typography } from 'antd'

interface NoTradeMessageCardProps {
  reason?: string
  text?: string
  noTradeReasons?: string[]
  recoveryConditions?: string[]
  marketSummary?: string
}

export function NoTradeMessageCard({
  reason,
  text,
  noTradeReasons = [],
  recoveryConditions = [],
  marketSummary,
}: NoTradeMessageCardProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="default">空仓 / 观察</Tag>
          {marketSummary ? <Tag>{marketSummary}</Tag> : null}
        </Space>

        <div>
          <Typography.Text className="section-kicker">Why We Pause</Typography.Text>
          <Typography.Paragraph style={{ margin: '8px 0 0', whiteSpace: 'pre-wrap' }}>
            {text || reason || '当前更适合先观察，不强行给票。'}
          </Typography.Paragraph>
        </div>

        {noTradeReasons.length > 0 ? (
          <div>
            <Typography.Text strong>为什么现在不做</Typography.Text>
            <List size="small" dataSource={noTradeReasons} renderItem={(item) => <List.Item>{item}</List.Item>} />
          </div>
        ) : null}

        {recoveryConditions.length > 0 ? (
          <div>
            <Typography.Text strong>接下来盯什么</Typography.Text>
            <List size="small" dataSource={recoveryConditions} renderItem={(item) => <List.Item>{item}</List.Item>} />
          </div>
        ) : null}
      </Space>
    </Card>
  )
}
