import { Space, Tag, Typography } from 'antd'
import type { HealthResponse, MarketBook, SessionListItem } from '../../../shared/contracts'
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

function fmtTime(value?: string | null) {
  if (!value) return '--:--'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function fmtCount(value?: number) {
  return new Intl.NumberFormat('zh-CN').format(value || 0)
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
  const tradeable = book?.daybook?.tradeable ?? false
  const storage = health?.storage

  return (
    <div className="header-bar">
      <div className="header-title-group">
        <Typography.Title level={3} style={{ margin: 0 }} className="header-title">
          GP Advisor
        </Typography.Title>
        <Typography.Text type="secondary" className="header-subtitle">
          聚合会话、推荐结果、持仓快照与上下文，在同一工作区内连续决策。
        </Typography.Text>
      </div>
      <div className="header-actions">
        <Space size={12} wrap className="header-status-grid">
          <Tag color={health?.llm_ready ? 'green' : 'red'}>
            {health?.llm_ready ? 'LLM 已连接' : 'LLM 未连接'}
          </Tag>
          <Tag>最近 5 分钟 {fmtTime(book?.last_closed_5m)}</Tag>
          <Tag color={tradeable ? 'green' : 'orange'}>{tradeable ? '当前可交易' : '当前观察中'}</Tag>
          <Tag>Sessions {fmtCount(storage?.session_count)}</Tag>
          <Tag>Messages {fmtCount(storage?.transcript_count)}</Tag>
          <Tag>Claims {fmtCount(storage?.claim_count)}</Tag>
          {storage?.latest_session_at ? <Tag>Last session {fmtTime(storage.latest_session_at)}</Tag> : null}
        </Space>
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
