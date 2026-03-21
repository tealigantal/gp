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
    <Card
      title="历史"
      style={{ height: '100%' }}
      styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' } }}
    >
      {/* Outer container provides height context; inner tabs/panels handle their own scroll */}
      <div style={{ flex: 1, minHeight: 0, height: '70vh', overflow: 'hidden' }}>
        <Tabs
          activeKey={tab}
          onChange={(k) => nav(`/history?tab=${encodeURIComponent(k)}`)}
          items={[
            { key: 'sessions', label: '会话', children: <Conversations /> },
            { key: 'search', label: '搜索', children: <Search /> },
          ]}
        />
      </div>
    </Card>
  )
}

