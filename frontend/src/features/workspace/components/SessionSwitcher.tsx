import { Button, Dropdown, Space, Typography } from 'antd'
import type { SessionListItem } from '../../../shared/contracts'

interface SessionSwitcherProps {
  sessions: SessionListItem[]
  currentId: string
  onSelect: (id: string) => void
  onNew: () => void
  loading?: boolean
}

function sessionStamp(value: string) {
  const date = new Date(value)
  return `${date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
}

export function SessionSwitcher({ sessions, currentId, onSelect, onNew, loading }: SessionSwitcherProps) {
  const items = sessions.map((session) => ({
    key: session.session_id,
    label: (
      <div className="session-menu-item">
        <Typography.Text strong ellipsis>
          {sessionStamp(session.updated_at)}
        </Typography.Text>
        <Typography.Text type="secondary" ellipsis className="session-menu-preview">
          {session.title || '未命名对话'} · {session.preview || ''}
        </Typography.Text>
      </div>
    ),
  }))

  const current = sessions.find((session) => session.session_id === currentId)

  return (
    <Space wrap className="session-switcher">
      <Dropdown
        menu={{
          items,
          onClick: (info) => onSelect(info.key),
        }}
        overlayClassName="session-dropdown"
        placement="bottomRight"
        trigger={['click']}
        disabled={!items.length}
      >
        <Button aria-label="Switch sessions" loading={loading} className="session-picker-btn">
          {current ? `选择对话档案 ${sessionStamp(current.updated_at)}` : '选择对话档案'}
        </Button>
      </Dropdown>
      <Button type="primary" onClick={onNew} aria-label="Start a new session" className="session-new-btn">
        + 新建对话
      </Button>
    </Space>
  )
}
