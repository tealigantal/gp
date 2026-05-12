import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { PickDetailArtifact } from '../../../shared/contracts'
import { executionStateMeta, recommendationStateMeta, riskLabel } from '../presentation'

interface PickDetailMessageCardProps {
  detail: PickDetailArtifact
  text: string
}

export function PickDetailMessageCard({ detail, text }: PickDetailMessageCardProps) {
  const state = executionStateMeta(detail.execution_state)
  const recommendationState =
    typeof detail.explain_context?.recommendation_state === 'string' ? detail.explain_context.recommendation_state : null
  const recommendation = recommendationStateMeta(recommendationState)
  const championStrategy =
    typeof detail.explain_context?.champion_strategy === 'string' ? detail.explain_context.champion_strategy : null

  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="blue">单票详情</Tag>
          <Tag>{detail.symbol}</Tag>
          {detail.rank ? <Tag>第 {detail.rank} 只</Tag> : null}
          {recommendationState ? <Tag color={recommendation.color}>{recommendation.label}</Tag> : null}
          {detail.execution_state ? <Tag color={state.color}>{state.label}</Tag> : null}
          {championStrategy ? <Tag color="geekblue">{championStrategy}</Tag> : null}
        </Space>

        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>

        <Descriptions size="small" column={2}>
          <Descriptions.Item label="买入区">{detail.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{detail.stop_text || detail.invalidation || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{detail.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="风险级别">{riskLabel(detail.risk_level)}</Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
