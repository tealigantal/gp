import { Card, Space, Tag, Typography } from 'antd'

interface FollowupTextMessageProps {
  content: string
  tags?: Array<{ label: string; value: string }>
}

export function FollowupTextMessage({ content, tags = [] }: FollowupTextMessageProps) {
  return (
    <Card size="small" className="followup-text-card">
      {tags.length ? (
        <Space size={8} wrap style={{ marginBottom: 6 }}>
          {tags.map((t) => (
            <Tag key={t.label} color="default">
              {t.label}：{t.value}
            </Tag>
          ))}
        </Space>
      ) : null}
      <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{content}</Typography.Paragraph>
    </Card>
  )
}
