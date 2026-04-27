import { Card, Space, Tag, Typography } from 'antd'
import type { CanonicalMessage, MarketBook } from '../../../shared/contracts'
import { fmtDateTime } from '../runtimeLabels'

interface MainConclusionCardProps {
  book?: MarketBook
  latestMessage?: CanonicalMessage
}

function resolveState(book?: MarketBook, latestMessage?: CanonicalMessage) {
  const run = latestMessage && 'run' in latestMessage ? latestMessage.run : null
  if (run?.run_action === 'NO_TRADE') {
    return {
      title: '今天先不硬做，优先等更清晰的交易机会。',
      tag: '空仓 / 观察',
      color: 'default' as const,
      reason: run.status_reason || '当前市场和执行条件不足以支撑强行开仓，先保留弹性。',
    }
  }
  if (run?.non_trading) {
    return {
      title: '先给下一交易窗口计划，不做“立刻买入”的盘中判断。',
      tag: '盘后计划',
      color: 'blue' as const,
      reason: run.status_reason || '当前不在连续竞价时段，先保留观察与执行计划，开盘后再看 5 分钟确认。',
    }
  }
  if (run?.run_action === 'DEGRADED') {
    return {
      title: '今天有计划，但执行上要更克制，先确认再动手。',
      tag: '降级观察',
      color: 'gold' as const,
      reason: run.status_reason || '环境偏弱或执行数据降级，重点等买点回到计划区间附近。',
    }
  }
  if (run?.run_action === 'RECOMMEND') {
    return {
      title: '当前有可跟踪计划，优先按买点和 5 分钟结构执行。',
      tag: '执行计划',
      color: 'green' as const,
      reason: run.status_reason || '不要只看排名，真正决定能不能做的是买点、失效位和 5 分钟结构。',
    }
  }
  return {
    title: '先在聊天里追问今天的机会、执行状态和风控。',
    tag: '等待提问',
    color: 'default' as const,
    reason: book?.daybook?.reason || '可以直接问“今天给我 3 只”或“第二个还能冲吗”。',
  }
}

export function MainConclusionCard({ book, latestMessage }: MainConclusionCardProps) {
  const state = resolveState(book, latestMessage)
  const updatedAt = fmtDateTime(book?.updated_at)
  const last5m = fmtDateTime(book?.last_closed_5m)

  return (
    <Card className="main-conclusion-card" styles={{ body: { display: 'flex', flexDirection: 'column', gap: 18 } }}>
      <div className="main-conclusion-hero">
        <div>
          <Typography.Text className="eyebrow">Market Brief</Typography.Text>
          <Typography.Title level={3} style={{ margin: '6px 0 0' }}>
            {state.title}
          </Typography.Title>
        </div>
        <Tag color={state.color}>{state.tag}</Tag>
      </div>
      <Typography.Paragraph className="hero-copy">{state.reason}</Typography.Paragraph>
      <Space wrap size={12}>
        <div className="mini-block">
          <Typography.Text strong>执行原则</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            先看买入区、失效位和 5 分钟结构，不因为排名靠前就直接追高。
          </Typography.Paragraph>
        </div>
        <div className="mini-block">
          <Typography.Text strong>最新 5 分钟</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0 }}>{last5m}</Typography.Paragraph>
        </div>
        <div className="mini-block">
          <Typography.Text strong>账本更新时间</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0 }}>{updatedAt}</Typography.Paragraph>
        </div>
      </Space>
    </Card>
  )
}
