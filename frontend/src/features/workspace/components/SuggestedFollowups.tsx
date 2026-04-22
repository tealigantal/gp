import { Button, Space } from 'antd'

interface SuggestedFollowupsProps {
  suggestions?: string[]
  onPick: (text: string) => void
}

export function SuggestedFollowups({ suggestions = [], onPick }: SuggestedFollowupsProps) {
  if (!suggestions.length) return null
  return (
    <Space size={8} wrap style={{ marginTop: 4 }}>
      {suggestions.map((text) => (
        <Button key={text} size="small" className="prompt-chip" onClick={() => onPick(text)}>
          {text}
        </Button>
      ))}
    </Space>
  )
}
