import { Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { CanonicalPick } from '../../../shared/contracts'
import { executionStateMeta, riskLabel } from '../presentation'

interface RecommendationPickCardProps {
  entry: CanonicalPick
  onPrompt?: (text: string) => void
}

export function RecommendationPickCard({ entry, onPrompt }: RecommendationPickCardProps) {
  const state = executionStateMeta(entry.execution_state)
  const dailyState = String(entry.data_provenance?.daily_freshness_state || '').toLowerCase()
  const dailyLastDate =
    typeof entry.data_provenance?.daily_last_date === 'string' ? String(entry.data_provenance.daily_last_date) : null
  const dailyColor = dailyState && dailyState !== 'current' ? 'volcano' : 'default'

  return (
    <Card size="small" className="recommendation-pick-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="pick-card-topline">
          <Space wrap>
            <div className="rank-dot">{entry.rank}</div>
            <div>
              <Typography.Text strong>
                {entry.code} {entry.name || ''}
              </Typography.Text>
              <div className="micro-copy">{entry.action === 'BUY' ? '优先执行计划' : '暂不入场'}</div>
            </div>
          </Space>
          <Space wrap>
            <Tag color={entry.can_execute_now ? 'green' : 'default'}>{entry.can_execute_now ? '计划区间内' : '先别追'}</Tag>
            <Tag color={state.color}>{state.label}</Tag>
            {dailyLastDate ? <Tag color={dailyColor}>日线截至 {dailyLastDate}</Tag> : null}
          </Space>
        </div>

        <Typography.Paragraph style={{ margin: 0 }}>{entry.thesis || '当前没有额外摘要。'}</Typography.Paragraph>

        <Descriptions size="small" column={2} className="pick-grid">
          <Descriptions.Item label="买入区">{entry.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{entry.stop_text || entry.invalidation || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{entry.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="风险级别">{riskLabel(entry.risk_level)}</Descriptions.Item>
          <Descriptions.Item label="综合分">{typeof entry.final_score === 'number' ? entry.final_score.toFixed(2) : '--'}</Descriptions.Item>
          <Descriptions.Item label="计划判断">{state.label}</Descriptions.Item>
        </Descriptions>

        <div>
          <Typography.Text strong>为什么它在这轮计划里</Typography.Text>
          <Typography.Paragraph style={{ margin: '6px 0 0' }}>{entry.why_selected || '当前计划仍然保留。'}</Typography.Paragraph>
        </div>

        <Space wrap>
          <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`为什么推荐 ${entry.symbol}`)}>
            为什么推荐这只
          </Button>
          <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`${entry.symbol} 现在还能买吗`)}>
            现在还能买吗
          </Button>
          <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`${entry.symbol} 的止盈止损点`)}>
            止盈止损点
          </Button>
          {entry.rank > 1 ? (
            <Button size="small" className="prompt-chip" onClick={() => onPrompt?.(`${entry.symbol} 和第一只比呢`)}>
              和第一只比
            </Button>
          ) : (
            <Button size="small" className="prompt-chip" onClick={() => onPrompt?.('第一只和第二只比呢')}>
              和第二只比
            </Button>
          )}
        </Space>
      </Space>
    </Card>
  )
}
