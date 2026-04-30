import { Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { CanonicalPick } from '../../../shared/contracts'
import { fmtPct } from '../../../shared/format'
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
              <div className="micro-copy">{entry.action === 'BUY' ? '优先执行计划' : '优先观察计划'}</div>
            </div>
          </Space>
          <Space wrap>
            <Tag color={entry.can_execute_now ? 'green' : 'default'}>{entry.can_execute_now ? '现在可执行' : '先别追'}</Tag>
            <Tag color={state.color}>{state.label}</Tag>
            {dailyLastDate ? <Tag color={dailyColor}>日线截止 {dailyLastDate}</Tag> : null}
          </Space>
        </div>

        <Typography.Paragraph style={{ margin: 0 }}>{entry.thesis || '当前没有额外摘要。'}</Typography.Paragraph>

        <Descriptions size="small" column={2} className="pick-grid">
          <Descriptions.Item label="买入区">{entry.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{entry.stop_text || entry.invalidation || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{entry.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="风险级别">{riskLabel(entry.risk_level)}</Descriptions.Item>
          <Descriptions.Item label="综合分">{typeof entry.final_score === 'number' ? entry.final_score.toFixed(2) : '--'}</Descriptions.Item>
          <Descriptions.Item label="执行判断">{state.label}</Descriptions.Item>
        </Descriptions>

        <div className="fact-strip">
          <Tag>距买点 {fmtPct(entry.entry_distance_pct, 2)}</Tag>
          <Tag>VWAP {entry.vwap?.toFixed(2) || '--'}</Tag>
          <Tag>相对量能 {entry.slot_rel_vol?.toFixed(2) || '--'}x</Tag>
          <Tag>RS {fmtPct(entry.rs_index, 2)}</Tag>
        </div>

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
              和第一只比呢
            </Button>
          ) : (
            <Button size="small" className="prompt-chip" onClick={() => onPrompt?.('第一只和第二只比呢')}>
              和第二只比呢
            </Button>
          )}
        </Space>
      </Space>
    </Card>
  )
}
