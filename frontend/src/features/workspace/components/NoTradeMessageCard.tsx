import { Card, Typography } from 'antd'

interface NoTradeMessageCardProps {
  reason?: string
  text?: string
}

export function NoTradeMessageCard({ reason, text }: NoTradeMessageCardProps) {
  return (
    <Card size="small">
      <Typography.Paragraph style={{ margin: 0 }}>
        {text || reason || '当前环境不宜交易，先观察。'}
      </Typography.Paragraph>
    </Card>
  )
}

