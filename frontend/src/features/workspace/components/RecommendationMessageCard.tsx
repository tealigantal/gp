import { Card, Space, Tag, Typography } from 'antd'
import type { CanonicalPick, CanonicalRunArtifact } from '../../../shared/contracts'
import { RecommendationPickCard } from './RecommendationPickCard'

interface RecommendationMessageCardProps {
  picks: CanonicalPick[]
  run?: CanonicalRunArtifact | null
  onPrompt?: (text: string) => void
}

export function RecommendationMessageCard({ picks, run, onPrompt }: RecommendationMessageCardProps) {
  const watchOnly = !run?.non_trading && picks.length > 0 && picks.every((entry) => entry.execution_state === 'WATCH_ONLY' || entry.execution_state === 'UNAVAILABLE')
  const title = run?.non_trading ? '下一交易窗口计划' : watchOnly ? '观察清单 / 候选跟踪' : '当前优先计划'
  const subtitle = run?.non_trading
    ? '现在不判断“立刻成交”，但可以先给出下一交易窗口的观察与执行计划。'
    : watchOnly
      ? '这一轮 run 保留了值得跟踪的标的，但当前盘中闸门或个股位置还没到能主动执行的状态。'
      : '下面的排序来自同一轮 run 的日线计划和最新执行状态，不是单纯按热度排序。'

  return (
    <Card className="recommendation-message-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <div>
            <Typography.Title level={5} style={{ margin: 0 }}>
              {title}
            </Typography.Title>
            <Typography.Paragraph type="secondary" style={{ margin: '4px 0 0' }}>
              {subtitle}
            </Typography.Paragraph>
          </div>
          <Space wrap>
            {run?.run_action ? <Tag>{run.run_action}</Tag> : null}
            {run?.market_phase ? <Tag>{run.market_phase}</Tag> : null}
            {run?.slot_status ? <Tag>{run.slot_status}</Tag> : null}
          </Space>
        </Space>
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {picks.map((entry) => (
            <RecommendationPickCard key={`${entry.rank}-${entry.symbol}`} entry={entry} onPrompt={onPrompt} />
          ))}
        </Space>
      </Space>
    </Card>
  )
}
