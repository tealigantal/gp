import { Card, Divider, Space, Tag, Typography } from 'antd'
import type { BoardEntry, MarketBook, SessionResponse, ChatResponse } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'

interface DecisionSnapshotProps {
  book?: MarketBook
  session?: SessionResponse
  latest?: ChatResponse | null
}

function statePill(entry: any) {
  if (!entry) return { text: '先观察', color: 'default', action: 'WATCH' as const }
  // CanonicalPick shape
  if (typeof entry.action === 'string') {
    if (entry.action === 'BUY') return { text: entry.state_label || '当前可买', color: 'green', action: 'BUY' as const }
    if (entry.action === 'INVALID') return { text: entry.state_label || '已失效', color: 'default', action: 'WATCH' as const }
    return { text: entry.state_label || '观察', color: 'orange', action: 'WATCH' as const }
  }
  // BoardEntry shape
  if (entry.can_open) return { text: '当前可买', color: 'green', action: 'BUY' as const }
  if (entry.invalidated) return { text: '先观察', color: 'default', action: 'WATCH' as const }
  return { text: '等回落', color: 'orange', action: 'WATCH' as const }
}

export function DecisionSnapshot({ book, session, latest }: DecisionSnapshotProps) {
  // 全部基于当前账本实时生成，不再读取最近回复缓存
  const top3: BoardEntry[] = (book?.board || []).slice(0, 3)
  const tradeable = book?.daybook?.tradeable ?? false
  const gate = tradeable ? 'ALLOW' : 'DENY'
  const freshness = (latest?.message as any)?.freshness_meta || {}
  const runId = latest?.run_id

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Typography.Title level={5} style={{ margin: 0 }}>当前决策快照</Typography.Title>

      <Card size="small">
        <Typography.Paragraph type="secondary" style={{ marginBottom: 8 }}>
          右侧只做辅助快照：当前是否可交易、最近 5 分钟时间、Top3 简表、市场提醒。它应该辅助，不应该成为主阅读区。
        </Typography.Paragraph>
        <Space size={6} wrap>
          <Tag color={tradeable ? 'green' : 'orange'}>当前状态：{tradeable ? '可交易' : '观察'}</Tag>
          <Tag>最近5分钟：{fmtTime(book?.last_closed_5m)}</Tag>
          <Tag color={tradeable ? 'green' : 'red'}>市场门控：{gate}</Tag>
          <Tag>当前会话：{session ? new Date(session.session.updated_at || session.session.created_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '--'}</Tag>
        </Space>
      </Card>

      <Card size="small" title="Freshness 元信息">
        <Space size={6} wrap>
          <Tag>run_id：{runId || '-'}</Tag>
          <Tag>book_version：{book?.book_version || '-'}</Tag>
          <Tag>daybook_effective_day：{(book as any)?.daybook_effective_day || freshness.daybook_effective_day || '-'}</Tag>
          <Tag>pulse_slot_at：{(book as any)?.pulse_slot_at || freshness.pulse_slot_at || '-'}</Tag>
          <Tag>market_phase：{(book as any)?.market_phase || freshness.market_phase || '-'}</Tag>
          <Tag>data_status：{(book as any)?.data_status || freshness.data_status || '-'}</Tag>
        </Space>
      </Card>

      <Card size="small" title="Top 3 快照">
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {top3.length === 0 ? (
            <Typography.Text type="secondary">暂无</Typography.Text>
          ) : (
            top3.map((e: BoardEntry, idx: number) => {
              const pill = statePill(e)
              const plan: any = (e?.pick as any)?.entry_plan || {}
              const entryText = (() => {
                const t = (plan.text || plan.desc || plan.range || '').toString().trim()
                if (t) return t
                const lo = plan.low, hi = plan.high, p = plan.price
                const norm = (v: any) => {
                  if (v === undefined || v === null) return ''
                  const n = Number(v)
                  return Number.isFinite(n) ? String(n) : String(v)
                }
                if (lo !== undefined && hi !== undefined) {
                  const a = norm(lo), b = norm(hi)
                  if (a && b) return `${a} - ${b}`
                }
                if (p !== undefined) {
                  const s = norm(p)
                  if (s) return s
                }
                return ''
              })()
              return (
                <Space key={e.symbol} style={{ width: '100%', justifyContent: 'space-between' }}>
                  <Typography.Text>
                    {idx + 1}. {e.symbol} {e.name ? ` ${e.name}` : ''}
                  </Typography.Text>
                  <Space size={6}>
                    {entryText ? (
                      <Typography.Text type="secondary">买入区间：{entryText}</Typography.Text>
                    ) : null}
                    <Tag>{pill.action}</Tag>
                    <Tag color={pill.color}>{pill.text}</Tag>
                  </Space>
                </Space>
              )
            })
          )}
        </Space>
      </Card>

      <Card size="small" title="当前排序（动作导向）">
        <Space direction="vertical" size={6} style={{ width: '100%' }}>
          {top3.map((e: BoardEntry, idx: number) => {
            const pill = statePill(e)
            return (
              <Space key={e.symbol} style={{ width: '100%', justifyContent: 'space-between' }}>
                <Typography.Text>#{idx + 1}</Typography.Text>
                <Typography.Text style={{ flex: 1, marginLeft: 8 }}>{e.symbol}</Typography.Text>
                <Typography.Text>{pill.action}</Typography.Text>
              </Space>
            )
          })}
        </Space>
      </Card>

      <Divider style={{ margin: '8px 0' }} />
      <Typography.Text type="secondary">此区为辅助信息，宽度保持克制。</Typography.Text>
    </Space>
  )
}
