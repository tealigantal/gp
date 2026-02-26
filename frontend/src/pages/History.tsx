import { Card, Tabs } from 'antd'
import { useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import Conversations from './Conversations'
import Search from './Search'

export default function History() {
  const loc = useLocation()
  const nav = useNavigate()
  const tab = useMemo(() => new URLSearchParams(loc.search).get('tab') || 'sessions', [loc.search])
  return (
    <Card title="历史">
      <Tabs
        activeKey={tab}
        onChange={(k) => nav(`/history?tab=${encodeURIComponent(k)}`)}
        items={[
          { key: 'sessions', label: '会话', children: <Conversations /> },
          { key: 'search', label: '搜索', children: <Search /> },
        ]}
      />
    </Card>
  )
}

