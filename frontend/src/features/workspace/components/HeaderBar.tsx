import { Space, Tag, Typography } from 'antd'
import type { HealthResponse, MarketBook, SessionResponse, SessionListItem } from '../../../shared/contracts'
import { SessionSwitcher } from './SessionSwitcher'

interface HeaderBarProps {
  sessionId: string
  onSessionIdChange: (value: string) => void
  onNewSession: () => void
  health?: HealthResponse
  bookVersion?: string | null
  session?: SessionResponse
  book?: MarketBook
  sessions: SessionListItem[]
}

export function HeaderBar({ health, book, sessions, sessionId, onSessionIdChange, onNewSession }: HeaderBarProps) {
  const tradeable = book?.daybook?.tradeable ?? false
  const latest5m = book?.last_closed_5m

  return (
    <div className="header-bar">
      <div>
        <Typography.Title level={3} style={{ margin: 0 }}>GP Advisor</Typography.Title>
        <Typography.Text type="secondary">
          聊天驱动 · 今日结论优先 · Top3 与执行性为先
        </Typography.Text>
      </div>
      <Space size={12} wrap>
        <Tag color={health?.llm_ready ? 'green' : 'red'}>{health?.llm_ready ? 'LLM 已就绪' : 'LLM 未就绪'}</Tag>
        <Tag>最新 5 分钟：{latest5m ? new Date(latest5m).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '--:--'}</Tag>
        <Tag color={tradeable ? 'green' : 'orange'}>当前状态：{tradeable ? '可交易' : '观察'}</Tag>
        <SessionSwitcher
          sessions={sessions}
          currentId={sessionId}
          onSelect={onSessionIdChange}
          onNew={onNewSession}
        />
      </Space>
    </div>
  )
}
