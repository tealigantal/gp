import { Card, Space, Tag, Typography } from 'antd'

interface ExitDecisionMessageProps {
  symbol: string
  view?: Record<string, unknown>
  text?: string
}

export function ExitDecisionMessage({ symbol, text }: ExitDecisionMessageProps) {
  return (
    <Card size="small">
      <Space size={8} wrap style={{ marginBottom: 6 }}>
        <Tag color="red">卖出判断</Tag>
        <Tag>{symbol}</Tag>
      </Space>
      <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
        {text || '结合计划与盘中状态，当前位置更建议减仓或退出。'}
      </Typography.Paragraph>
    </Card>
  )
}
