import { Button, Input, Space, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import type { HealthResponse } from '../../../shared/contracts'

interface HeaderBarProps {
  sessionId: string
  onSessionIdChange: (value: string) => void
  onNewSession: () => void
  health?: HealthResponse
  bookVersion?: string | null
}

export function HeaderBar({ sessionId, onSessionIdChange, onNewSession, health, bookVersion }: HeaderBarProps) {
  const [draftSessionId, setDraftSessionId] = useState(sessionId)

  useEffect(() => {
    setDraftSessionId(sessionId)
  }, [sessionId])

  return (
    <div className="header-bar">
      <div>
        <Typography.Title level={4} style={{ margin: 0 }}>
          GP Advisor Workspace
        </Typography.Title>
        <Typography.Text type="secondary">
          单一对话主链 · Session Truth / Market Book / Advice Run
        </Typography.Text>
      </div>
      <Space size={12} wrap>
        <Tag color={health?.llm_ready ? 'green' : 'red'}>{health?.llm_ready ? 'LLM Ready' : 'LLM Offline'}</Tag>
        <Tag>{health?.trading_day || 'No Day'}</Tag>
        <Tag>{bookVersion || health?.book_version || 'No Book'}</Tag>
        <Input
          value={draftSessionId}
          onChange={(event) => setDraftSessionId(event.target.value)}
          onPressEnter={() => onSessionIdChange(draftSessionId)}
          className="session-input"
          placeholder="session id"
        />
        <Button onClick={() => onSessionIdChange(draftSessionId)}>切换会话</Button>
        <Button onClick={onNewSession}>新会话</Button>
      </Space>
    </div>
  )
}
