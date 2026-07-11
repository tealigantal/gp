import { Space, Tag, Typography } from 'antd'
import type { HealthResponse, MarketBook, SessionListItem } from '../../../shared/contracts'
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
  const dailyStatus = String(health?.runtime?.daily_data_state || health?.runtime?.daily_status || '').toLowerCase()
  const artifactFreshness = String(health?.runtime?.artifact_freshness || '').toLowerCase()
  if (dailyStatus === 'freshness_blocked') {
    return { color: 'volcano' as const, text: '日线未就绪' }
  }
  if (dailyStatus === 'eod_pending') {
    return { color: 'gold' as const, text: '等待收盘日线' }
  }
  if (artifactFreshness === 'lagging' || (!artifactFreshness && dailyStatus === 'artifact_lagging')) {
    return { color: 'volcano' as const, text: '等待日线更新' }
  }
  const slotStatus = String(book?.slot_status || '').toUpperCase()
  if (slotStatus && slotStatus !== 'OK') {
    return { color: 'gold' as const, text: '数据受限' }
  }
  if (health?.runtime?.book_freshness === 'lagging') {
    return { color: 'volcano' as const, text: '等待日线更新' }
  }
  if (health?.runtime?.tradeability_state === 'tradeable' || book?.publish_allowed) {
    return { color: 'green' as const, text: '日线计划' }
  }
  if (String(book?.market_phase || health?.runtime?.market_phase || '').toUpperCase() === 'NON_TRADING' && (book?.board || []).length > 0) {
    return { color: 'blue' as const, text: '下个交易日计划' }
  }
  return { color: 'default' as const, text: '暂不入场' }
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
          围绕日线计划回答候选、买入区、失效位、止盈位和条件变化。
        </Typography.Paragraph>
        <Space size={[8, 8]} wrap className="header-status-grid">
          <Tag color={health?.llm_ready ? 'green' : 'red'}>{health?.llm_ready ? '自然语言已接通' : '自然语言未接通'}</Tag>
          <Tag>数据源 {health?.runtime?.data_provider || '--'}</Tag>
          <Tag>自动更新 {health?.runtime?.auto_update_service || 'gp-worker'}</Tag>
          <Tag color={freshness.color}>{freshness.label}</Tag>
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
