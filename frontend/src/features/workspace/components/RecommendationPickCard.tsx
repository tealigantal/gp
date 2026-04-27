import { Button, Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { CanonicalPick } from '../../../shared/contracts'

interface RecommendationPickCardProps {
  entry: CanonicalPick
  onPrompt?: (text: string) => void
}

function stateMeta(entry: CanonicalPick) {
  const mapping: Record<string, { color: string; label: string }> = {
    BUY_NOW: { color: 'green', label: '可执行' },
    WAIT_PULLBACK: { color: 'gold', label: '等回踩' },
    WAIT_NEXT_SESSION: { color: 'blue', label: '下一交易窗口' },
    WATCH_ONLY: { color: 'default', label: '仅观察' },
    RISK_HIGH: { color: 'volcano', label: '风险偏高' },
    INVALIDATED: { color: 'red', label: '已失效' },
    UNAVAILABLE: { color: 'default', label: '数据降级' },
  }
  return mapping[entry.execution_state] || { color: 'default', label: entry.execution_state }
}

function pct(value?: number | null) {
  if (value == null || Number.isNaN(value)) return '--'
  return `${(value * 100).toFixed(2)}%`
}

export function RecommendationPickCard({ entry, onPrompt }: RecommendationPickCardProps) {
  const state = stateMeta(entry)
  const dailyState = String(entry.data_provenance?.daily_freshness_state || '').toLowerCase()
  const dailyLastDate = typeof entry.data_provenance?.daily_last_date === 'string' ? String(entry.data_provenance.daily_last_date) : null
  const dailyColor = dailyState && dailyState !== 'current' ? 'volcano' : 'default'

  return (
    <Card size="small" className="recommendation-pick-card">
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space wrap>
            <div className="rank-dot">{entry.rank}</div>
            <div>
              <Typography.Text strong>
                {entry.code} {entry.name || ''}
              </Typography.Text>
              <div className="micro-copy">{entry.action === 'BUY' ? '计划买入' : '观察计划'}</div>
            </div>
          </Space>
          <Space wrap>
            <Tag color={entry.can_execute_now ? 'green' : 'default'}>{entry.can_execute_now ? '现在可执行' : '现在先别追'}</Tag>
            <Tag color={state.color}>{state.label}</Tag>
            {dailyLastDate ? <Tag color={dailyColor}>日线截止 {dailyLastDate}</Tag> : null}
          </Space>
        </Space>

        <Typography.Paragraph style={{ margin: 0 }}>{entry.thesis || '暂无 thesis'}</Typography.Paragraph>

        <Descriptions size="small" column={2} className="pick-grid">
          <Descriptions.Item label="买入区">{entry.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{entry.stop_text || entry.invalidation || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{entry.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="风险">{entry.risk_level || 'medium'}</Descriptions.Item>
          <Descriptions.Item label="综合分">{typeof entry.final_score === 'number' ? entry.final_score.toFixed(2) : '--'}</Descriptions.Item>
          <Descriptions.Item label="执行状态">{entry.execution_state}</Descriptions.Item>
        </Descriptions>

        <div className="fact-strip">
          <Tag>距买点 {pct(entry.entry_distance_pct)}</Tag>
          <Tag>VWAP {entry.vwap?.toFixed(2) || '--'}</Tag>
          <Tag>相对量能 {entry.slot_rel_vol?.toFixed(2) || '--'}x</Tag>
          <Tag>RS {pct(entry.rs_index)}</Tag>
        </div>

        <div>
          <Typography.Text type="secondary">入选原因</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0 }}>{entry.why_selected || '当前计划保留。'}</Typography.Paragraph>
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
