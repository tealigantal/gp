import { Button, Dropdown, Space, Typography } from 'antd'
import type { SessionListItem } from '../../../shared/contracts'

interface SessionSwitcherProps {
  sessions: SessionListItem[]
  currentId: string
  onSelect: (id: string) => void
  onNew: () => void
}

export function SessionSwitcher({ sessions, currentId, onSelect, onNew }: SessionSwitcherProps) {
  const items = sessions.map((s) => ({
    key: s.session_id,
    label: (
      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 220 }}>
        <Typography.Text strong>
          {new Date(s.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })}
          {' '}
          {new Date(s.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </Typography.Text>
        <Typography.Text type="secondary" ellipsis>
          {s.title || '会话'} · {s.preview || ''}
        </Typography.Text>
      </div>
    ),
  }))

  const current = sessions.find((s) => s.session_id === currentId)
  const currentLabel = current
    ? `${new Date(current.updated_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })} ${new Date(current.updated_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
    : '新会话'

  return (
    <Space>
      <Dropdown
        menu={{
          items,
          onClick: (info) => onSelect(info.key),
        }}
        placement="bottomRight"
      >
        <Button>{currentLabel}</Button>
      </Dropdown>
      <Button type="primary" onClick={onNew}>
        新会话
      </Button>
    </Space>
  )
}

