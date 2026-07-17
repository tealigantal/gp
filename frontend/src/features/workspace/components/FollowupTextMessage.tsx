import { Card, Space, Tag, Typography } from 'antd'

interface FollowupTextMessageProps {
  content: string
  label?: string
  tags?: Array<{ label: string; value: string }>
}

export function FollowupTextMessage({ content, label = '继续说明', tags = [] }: FollowupTextMessageProps) {
  return (
    <Card size="small" className="followup-text-card">
      <Typography.Text className="section-kicker">{label}</Typography.Text>
      {tags.length ? (
        <Space size={8} wrap style={{ marginTop: 10, marginBottom: 6 }}>
          {tags.map((t) => (
            <Tag key={t.label} color="default">
              {t.label}：{t.value}
            </Tag>
          ))}
        </Space>
      ) : null}
      <Typography.Paragraph style={{ margin: '10px 0 0', whiteSpace: 'pre-wrap' }}>{content}</Typography.Paragraph>
    </Card>
  )
}
