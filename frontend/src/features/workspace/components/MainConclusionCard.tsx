import { Card, Space, Tag, Typography } from 'antd'
import type { MarketBook } from '../../../shared/contracts'

interface MainConclusionCardProps {
  book?: MarketBook
}

export function MainConclusionCard({ book }: MainConclusionCardProps) {
  const tradeable = book?.daybook?.tradeable ?? false
  const reason = book?.daybook?.reason || ''
  const last5m = book?.last_closed_5m || null
  const updated = book?.updated_at || null
  return (
    <Card
      className="main-conclusion-card"
      style={{ background: '#0f172a', color: '#e5f2ff', borderRadius: 16 }}
      bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 10 }}
      title={
        <Space size={8}>
          <Typography.Title level={4} style={{ color: '#e5f2ff', margin: 0 }}>今日主结论</Typography.Title>
          <Typography.Text style={{ color: '#c7d2fe' }}>{tradeable ? '可以交易（以计划与盘中条件为准）' : '暂不交易，先观察'}</Typography.Text>
        </Space>
      }
      extra={<Tag color={tradeable ? 'green' : 'red'}>{tradeable ? 'ALLOW' : 'DENY'}</Tag>}
      headStyle={{ background: 'transparent', borderBottom: '1px solid rgba(148,163,184,0.18)' }}
    >
      <Space wrap size={14}>
        <div className="mini-block">
          <Typography.Text strong style={{ color: '#93c5fd' }}>市场摘要</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0, color: '#e5f2ff' }}>{reason || '依据当前账本生成。'}</Typography.Paragraph>
        </div>
        <div className="mini-block">
          <Typography.Text strong style={{ color: '#93c5fd' }}>执行原则</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0, color: '#e5f2ff' }}>{tradeable ? '只在满足计划与风险收益条件下操作，避免追高。' : '保持观察，等待条件满足后再行动。'}</Typography.Paragraph>
        </div>
        <div className="mini-block">
          <Typography.Text strong style={{ color: '#93c5fd' }}>盘中提醒</Typography.Text>
          <Typography.Paragraph style={{ marginBottom: 0, color: '#e5f2ff' }}>
            最近 5 分钟：{last5m ? new Date(last5m).toLocaleString('zh-CN', { hour12: false }) : '—'}；账本更新时间：{updated ? new Date(updated).toLocaleString('zh-CN', { hour12: false }) : '—'}
          </Typography.Paragraph>
        </div>
      </Space>
    </Card>
  )
}

