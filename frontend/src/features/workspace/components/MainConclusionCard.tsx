import { Card, Space, Tag, Typography } from 'antd'
import type { MarketBook } from '../../../shared/contracts'

interface MainConclusionCardProps {
  book?: MarketBook
}

function fmtDateTime(value?: string | null) {
  if (!value) return '暂无'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { hour12: false })
}

export function MainConclusionCard({ book }: MainConclusionCardProps) {
  const tradeable = book?.daybook?.tradeable ?? false
  const reason = book?.daybook?.reason || '基于当前账本状态整理，等待更明确的盘中条件。'
  const updatedAt = fmtDateTime(book?.updated_at)
  const last5m = fmtDateTime(book?.last_closed_5m)

  return (
    <Card className="main-conclusion-card" styles={{ body: { display: 'flex', flexDirection: 'column', gap: 18 } }}>
      <div className="main-conclusion-hero">
        <div>
          <Typography.Text className="eyebrow">Market Brief</Typography.Text>
          <Typography.Title level={3} style={{ margin: '6px 0 0' }}>
            {tradeable ? '当前允许按计划观察与执行' : '当前以观察为主，不建议贸然开仓'}
          </Typography.Title>
        </div>
        <Tag color={tradeable ? 'green' : 'orange'}>{tradeable ? '可执行' : '观察'}</Tag>
      </div>

      <Typography.Paragraph className="hero-copy">{reason}</Typography.Paragraph>

      <Space wrap size={12}>
        <div className="mini-block">
          <Typography.Text strong>执行原则</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0 }}>
            先看计划买点、风险收益比和 5 分钟状态，不因排名靠前就提前追单。
          </Typography.Paragraph>
        </div>
        <div className="mini-block">
          <Typography.Text strong>最近 5 分钟</Typography.Text>
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
