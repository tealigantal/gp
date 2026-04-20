import { Card, Space, Typography } from 'antd'
import type { CanonicalPick } from '../../../shared/contracts'
import { RecommendationPickCard } from './RecommendationPickCard'

interface RecommendationMessageCardProps {
  picks: CanonicalPick[]
  onPrompt?: (text: string) => void
}

export function RecommendationMessageCard({ picks, onPrompt }: RecommendationMessageCardProps) {
  return (
    <Card className="recommendation-message-card" bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Paragraph style={{ margin: 0 }}>
        以下是当前的前 3 只候选（结构化推荐）。
      </Typography.Paragraph>
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        {picks.map((e) => (
          <RecommendationPickCard key={`${e.rank}-${e.symbol}`} entry={e} onPrompt={onPrompt} />
        ))}
      </Space>
    </Card>
  )
}
