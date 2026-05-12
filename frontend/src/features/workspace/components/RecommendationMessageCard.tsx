import { Card, Space, Tag, Typography } from 'antd'
import type { CanonicalPick, CanonicalRunArtifact, RuntimeStatus } from '../../../shared/contracts'
import { recommendationStateMeta, runStateMeta, runActionLabel, slotStatusLabel } from '../presentation'
import { marketPhaseLabel } from '../runtimeLabels'
import { RecommendationPickCard } from './RecommendationPickCard'

interface RecommendationMessageCardProps {
  picks: CanonicalPick[]
  run?: CanonicalRunArtifact | null
  runtime?: RuntimeStatus | null
  onPrompt?: (text: string) => void
}

export function RecommendationMessageCard({ picks, run, runtime, onPrompt }: RecommendationMessageCardProps) {
  const state = runStateMeta(run, { runtime })
  const recommendation = recommendationStateMeta(run?.recommendation_state)

  return (
    <Card className="recommendation-message-card">
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <div className="message-card-header">
          <div>
            <Typography.Text className="section-kicker">Plan Set</Typography.Text>
            <Typography.Title level={5} style={{ margin: '4px 0 0' }}>
              {state.badge.label}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>
              {state.summary}
            </Typography.Paragraph>
          </div>
          <Space wrap>
            {run?.recommendation_state ? <Tag color={recommendation.color}>{recommendation.label}</Tag> : null}
            {run?.run_action ? <Tag>{runActionLabel(run.run_action)}</Tag> : null}
            {run?.market_phase ? <Tag>{marketPhaseLabel(run.market_phase)}</Tag> : null}
            {run?.slot_status ? <Tag>{slotStatusLabel(run.slot_status)}</Tag> : null}
            {run?.slot_id ? <Tag>{run.slot_id}</Tag> : null}
          </Space>
        </div>

        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {picks.map((entry) => (
            <RecommendationPickCard key={`${entry.rank}-${entry.symbol}`} entry={entry} onPrompt={onPrompt} />
          ))}
        </Space>
      </Space>
    </Card>
  )
}
