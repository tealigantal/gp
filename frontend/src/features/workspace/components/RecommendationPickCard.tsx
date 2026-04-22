import { Button, Card, Space, Tag, Typography } from 'antd'
import type { CanonicalPick } from '../../../shared/contracts'

interface RecommendationPickCardProps {
  entry: CanonicalPick
  onPrompt?: (text: string) => void
}

function statePill(entry: CanonicalPick) {
  if (entry.action === 'BUY') return { text: entry.state_label || '当前可买', color: 'green', action: 'BUY' }
  if (entry.action === 'INVALID') return { text: entry.state_label || '已失效', color: 'default', action: 'WATCH' }
  return { text: entry.state_label || '观察', color: 'orange', action: 'WATCH' }
}

export function RecommendationPickCard({ entry, onPrompt }: RecommendationPickCardProps) {
  const pill = statePill(entry)
  return (
    <Card size="small" className="recommendation-pick-card" styles={{ body: { display: 'flex', flexDirection: 'column', gap: 8 } }}>
      <Space style={{ justifyContent: 'space-between' }}>
        <Space>
          <div className="rank-dot">{entry.rank}</div>
          <Typography.Text strong>
            {entry.symbol}{entry.name ? ` ${entry.name}` : ''}
          </Typography.Text>
        </Space>
        <Space size={6}>
          <Tag>{pill.action}</Tag>
          <Tag color={pill.color}>{pill.text}</Tag>
        </Space>
      </Space>
      {entry.thesis ? <Typography.Paragraph style={{ margin: 0 }}>{entry.thesis}</Typography.Paragraph> : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
        {entry.entry_text ? (
          <div>
            <Typography.Text type="secondary">入场计划</Typography.Text>
            <div>{entry.entry_text}</div>
          </div>
        ) : null}
        {entry.stop_text ? (
          <div>
            <Typography.Text type="secondary">止损计划</Typography.Text>
            <div>{entry.stop_text}</div>
          </div>
        ) : null}
        {entry.take_text ? (
          <div>
            <Typography.Text type="secondary">止盈计划</Typography.Text>
            <div>{entry.take_text}</div>
          </div>
        ) : null}
      </div>
      <div>
        <Typography.Text type="secondary">入选原因</Typography.Text>
        {entry.why_selected_text ? <Typography.Paragraph style={{ margin: 0 }}>{entry.why_selected_text}</Typography.Paragraph> : null}
      </div>
      <Space size={8} wrap>
        <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`为什么推荐 ${entry.symbol}`)}>
          为什么推荐 {entry.symbol}
        </Button>
        <Button size="small" className="prompt-chip" onClick={() => onPrompt?.('它和其他候选相比强在哪里')}>
          和其他候选相比
        </Button>
        <Button size="small" className="prompt-chip" onClick={() => onPrompt?.('这只票现在还能买吗')}>
          现在还能买吗
        </Button>
        <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`给我 ${entry.symbol} 的止盈止损建议`)}>
          止盈止损建议
        </Button>
      </Space>
    </Card>
  )
}
