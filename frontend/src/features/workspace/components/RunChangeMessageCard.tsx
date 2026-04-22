import { Card, Tag, Typography } from 'antd'

interface RunChangeMessageCardProps {
  text: string
}

export function RunChangeMessageCard({ text }: RunChangeMessageCardProps) {
  return (
    <Card size="small">
      <Tag color="purple">本轮 vs 上轮</Tag>
      <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
    </Card>
  )
}

