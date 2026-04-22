import { Card, Tag, Typography } from 'antd'

interface LiveCheckMessageCardProps {
  text: string
}

export function LiveCheckMessageCard({ text }: LiveCheckMessageCardProps) {
  return (
    <Card size="small">
      <Tag color="blue">盘中状态</Tag>
      <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
    </Card>
  )
}

