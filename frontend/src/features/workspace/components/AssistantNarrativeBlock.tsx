import { Card, Typography } from 'antd'

export function AssistantNarrativeBlock({ text }: { text: string }) {
  return (
    <Card size="small" style={{ borderRadius: 12 }}>
      <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
    </Card>
  )
}

