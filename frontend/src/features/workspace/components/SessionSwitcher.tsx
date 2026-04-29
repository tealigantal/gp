import { Button, Dropdown, Space, Typography } from 'antd'
import type { SessionListItem } from '../../../shared/contracts'

interface SessionSwitcherProps {
  sessions: SessionListItem[]
  currentId: string
  onSelect: (id: string) => void
  onNew: () => void
  loading?: boolean
}

export function SessionSwitcher({ sessions, currentId, onSelect, onNew, loading }: SessionSwitcherProps) {
  const items = sessions.map((session) => ({
    key: session.session_id,
    label: (
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 240 }}>
        <Typography.Text strong>
          {new Date(session.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}{' '}
          {new Date(session.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </Typography.Text>
        <Typography.Text type="secondary" ellipsis>
          {session.title || '未命名会话'} · {session.preview || ''}
        </Typography.Text>
      </div>
    ),
  }))

  const current = sessions.find((session) => session.session_id === currentId)
  const currentLabel = current
    ? `${new Date(current.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${new Date(current.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
    : '当前会话'

  return (
    <Space wrap className="session-switcher">
      <Dropdown
        menu={{
          items,
          onClick: (info) => onSelect(info.key),
        }}
        placement="bottomRight"
        trigger={['click']}
        disabled={!items.length}
      >
        <Button aria-label="Switch sessions" loading={loading} className="session-picker-btn">
          {currentLabel}
        </Button>
      </Dropdown>
      <Button type="primary" onClick={onNew} aria-label="Start a new session" className="session-new-btn">
        新建会话
      </Button>
    </Space>
  )
}
