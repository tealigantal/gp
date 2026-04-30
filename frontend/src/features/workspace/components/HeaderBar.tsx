import { Space, Tag, Typography } from 'antd'
import type { HealthResponse, MarketBook, SessionListItem } from '../../../shared/contracts'
import { isIntradayEnabled } from '../presentation'
import { fmtDateTime, runtimeFreshnessMeta } from '../runtimeLabels'
import { SessionSwitcher } from './SessionSwitcher'

interface HeaderBarProps {
  sessionId: string
  onSessionIdChange: (value: string) => void
  onNewSession: () => void
  health?: HealthResponse
  book?: MarketBook
  sessions: SessionListItem[]
  isSessionSwitching?: boolean
}

function fmtCount(value?: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
}

function currentBookState(book?: MarketBook, health?: HealthResponse) {
  if (!isIntradayEnabled(health?.runtime)) {
    return { color: 'blue' as const, text: '日线模式' }
  }
  const slotStatus = String(book?.slot_status || '').toUpperCase()
  if (slotStatus && slotStatus !== 'OK') {
    return { color: 'gold' as const, text: '执行数据降级' }
  }
  if (health?.runtime?.book_freshness === 'lagging') {
    return { color: 'volcano' as const, text: '等待 worker 补齐' }
  }
  if (book?.publish_allowed) {
    return { color: 'green' as const, text: '盘中可执行' }
  }
  if (health?.runtime?.book_freshness === 'postclose_ready' || health?.runtime?.book_freshness === 'non_trading') {
    return { color: 'blue' as const, text: '下一交易窗口' }
  }
  return { color: 'default' as const, text: '观察中' }
}

export function HeaderBar({
  health,
  book,
  sessions,
  sessionId,
  onSessionIdChange,
  onNewSession,
  isSessionSwitching,
}: HeaderBarProps) {
  const storage = health?.storage
  const stateTag = currentBookState(book, health)
  const freshness = runtimeFreshnessMeta(health?.runtime)
  const intradayEnabled = isIntradayEnabled(health?.runtime)

  return (
    <div className="header-bar">
      <div className="header-title-group">
        <div className="header-brand-row">
          <Typography.Text className="brand-chip">GP</Typography.Text>
          <Typography.Title level={3} style={{ margin: 0 }} className="header-title">
            GP 对话助手
          </Typography.Title>
          <Typography.Text className="header-title-meta">A股交易顾问工作台</Typography.Text>
          <Tag color={stateTag.color} className="header-state-pill">
            {stateTag.text}
          </Tag>
        </div>
        <Typography.Paragraph className="header-subtitle">
          像一个会记住上下文的交易助手一样回答你：不给内部字段，不打断判断链，重点把“为什么、现在怎么做、什么条件下会变”讲清楚。
        </Typography.Paragraph>
        <Space size={[8, 8]} wrap className="header-status-grid">
          <Tag color={health?.llm_ready ? 'green' : 'red'}>{health?.llm_ready ? '自然语言已接通' : '自然语言未接通'}</Tag>
          <Tag>数据源 {health?.runtime?.data_provider || '--'}</Tag>
          <Tag>自动更新 {health?.runtime?.auto_update_service || 'gp-worker'}</Tag>
          <Tag color={freshness.color}>{freshness.label}</Tag>
          <Tag>{intradayEnabled ? `最新 5 分钟 ${fmtDateTime(book?.last_closed_5m)}` : '盘中 5 分钟已停用'}</Tag>
          <Tag>会话 {fmtCount(storage?.session_count)}</Tag>
          <Tag>消息 {fmtCount(storage?.transcript_count)}</Tag>
          <Tag>Claims {fmtCount(storage?.claim_count)}</Tag>
          {storage?.latest_session_at ? <Tag>最近活跃 {fmtDateTime(storage.latest_session_at)}</Tag> : null}
        </Space>
      </div>
      <div className="header-actions">
        <SessionSwitcher
          sessions={sessions}
          currentId={sessionId}
          onSelect={onSessionIdChange}
          onNew={onNewSession}
          loading={isSessionSwitching}
        />
      </div>
    </div>
  )
}
