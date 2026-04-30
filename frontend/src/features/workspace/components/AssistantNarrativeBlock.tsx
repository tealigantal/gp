import { Card, Typography } from 'antd'

export function AssistantNarrativeBlock({ text }: { text: string }) {
  return (
    <Card size="small" className="narrative-card">
      <Typography.Text className="section-kicker">Why This Answer</Typography.Text>
      <Typography.Paragraph style={{ margin: '8px 0 0', whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
    </Card>
  )
}
