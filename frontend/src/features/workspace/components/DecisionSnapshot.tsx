import { Card, Divider, Space, Tag, Typography } from 'antd'
import type { BoardEntry, CanonicalPick, ChatResponse, MarketBook, SessionResponse } from '../../../shared/contracts'

interface DecisionSnapshotProps {
  book?: MarketBook
  session?: SessionResponse
  latest?: ChatResponse | null
}

function fmtDateTime(value?: string | null) {
  if (!value) return '--'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { hour12: false })
}

function resolveAction(entry: BoardEntry) {
  if (entry.invalidated) return { text: '已失效', color: 'default' as const, action: 'INVALID' }
  if (entry.can_open) return { text: '可执行', color: 'green' as const, action: 'BUY' }
  return { text: '观察', color: 'orange' as const, action: 'WATCH' }
}

function resolveCanonicalAction(entry: CanonicalPick) {
  if (entry.action === 'INVALID') return { text: entry.state_label || '已失效', color: 'default' as const, action: 'INVALID' }
  if (entry.action === 'BUY') return { text: entry.state_label || '可执行', color: 'green' as const, action: 'BUY' }
  return { text: entry.state_label || '观察', color: 'orange' as const, action: 'WATCH' }
}

function entryPlanText(entry: BoardEntry) {
  const plan = entry.pick?.entry_plan || {}
  const direct = [plan.text, plan.desc, plan.range].find((item) => typeof item === 'string' && item.trim())
  if (typeof direct === 'string') return direct.trim()
  if (plan.low != null && plan.high != null) return `${plan.low} - ${plan.high}`
  if (plan.price != null) return String(plan.price)
  return '待确认'
}

function canonicalPlanText(entry: CanonicalPick) {
  return entry.entry_text || '待确认'
}

function pickTop3(latest?: ChatResponse | null): CanonicalPick[] {
  const panel = latest?.right_panel as { top3?: unknown[] } | undefined
  return Array.isArray(panel?.top3) ? (panel.top3 as CanonicalPick[]) : []
}

export function DecisionSnapshot({ book, session, latest }: DecisionSnapshotProps) {
  const latestTop3 = pickTop3(latest)
  const fallbackTop3 = latestTop3.length > 0 ? [] : (book?.board || []).slice(0, 3)
  const latestMessage = latest?.message
  const freshnessMeta =
    latestMessage && 'freshness_meta' in latestMessage
      ? ((latestMessage as { freshness_meta?: Record<string, unknown> }).freshness_meta || {})
      : {}

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <div>
        <Typography.Text className="eyebrow">Workspace Snapshot</Typography.Text>
        <Typography.Title level={4} style={{ margin: '4px 0 0' }}>
          当前决策快照
        </Typography.Title>
      </div>

      <Card className="snapshot-card" size="small">
        <Space size={8} wrap>
          <Tag color={book?.daybook?.tradeable ? 'green' : 'orange'}>
            {book?.daybook?.tradeable ? '可交易' : '观察中'}
          </Tag>
          <Tag>会话更新时间 {fmtDateTime(session?.session?.updated_at || session?.session?.created_at)}</Tag>
          <Tag>账本版本 {book?.book_version || '--'}</Tag>
        </Space>
      </Card>

      <Card className="snapshot-card" size="small" title="时效信息">
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <Typography.Text>最近 5 分钟：{fmtDateTime(book?.last_closed_5m)}</Typography.Text>
          <Typography.Text>Daybook 生效日：{String(freshnessMeta.daybook_effective_day || book?.daybook_effective_day || '--')}</Typography.Text>
          <Typography.Text>Pulse 时间点：{String(freshnessMeta.pulse_slot_at || book?.pulse_slot_at || '--')}</Typography.Text>
          <Typography.Text>市场阶段：{String(freshnessMeta.market_phase || book?.market_phase || '--')}</Typography.Text>
        </Space>
      </Card>

      <Card className="snapshot-card" size="small" title="Top 3 候选">
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {latestTop3.length === 0 && fallbackTop3.length === 0 ? (
            <Typography.Text type="secondary">当前没有候选。</Typography.Text>
          ) : (
            <>
              {latestTop3.map((entry) => {
                const action = resolveCanonicalAction(entry)
                return (
                  <div key={entry.symbol} className="snapshot-row">
                    <div>
                      <Typography.Text strong>
                        #{entry.rank} {entry.symbol} {entry.name || ''}
                      </Typography.Text>
                      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {entry.reason_short || entry.thesis || '暂无摘要'}
                      </Typography.Paragraph>
                    </div>
                    <Space size={6} wrap>
                      <Tag>{action.action}</Tag>
                      <Tag color={action.color}>{action.text}</Tag>
                      <Tag>{canonicalPlanText(entry)}</Tag>
                    </Space>
                  </div>
                )
              })}
              {fallbackTop3.map((entry) => {
                const action = resolveAction(entry)
                return (
                  <div key={entry.symbol} className="snapshot-row">
                    <div>
                      <Typography.Text strong>
                        #{entry.rank} {entry.symbol} {entry.name || ''}
                      </Typography.Text>
                      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {entry.summary || entry.pick?.thesis || '暂无摘要'}
                      </Typography.Paragraph>
                    </div>
                    <Space size={6} wrap>
                      <Tag>{action.action}</Tag>
                      <Tag color={action.color}>{action.text}</Tag>
                      <Tag>{entryPlanText(entry)}</Tag>
                    </Space>
                  </div>
                )
              })}
            </>
          )}
        </Space>
      </Card>

      <Divider style={{ margin: '4px 0' }} />
      <Typography.Text type="secondary">右侧只保留用户态决策信息，不展示内部调试轨迹。</Typography.Text>
    </Space>
  )
}
