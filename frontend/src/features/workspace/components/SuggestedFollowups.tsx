import { Space, Tag } from 'antd'

interface SuggestedFollowupsProps {
  suggestions?: string[]
  onPick: (text: string) => void
}

export function SuggestedFollowups({ suggestions = [], onPick }: SuggestedFollowupsProps) {
  if (!suggestions.length) return null
  return (
    <Space size={8} wrap style={{ marginTop: 4 }}>
      {suggestions.map((t) => (
        <Tag key={t} style={{ cursor: 'pointer', background: '#f1f5f9' }} onClick={() => onPick(t)}>
          {t}
        </Tag>
      ))}
    </Space>
  )
}
