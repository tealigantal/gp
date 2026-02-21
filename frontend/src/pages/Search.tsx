import { useState } from 'react'
import { Card, Input, Button, List, Space, Typography } from 'antd'
import { search as apiSearch, listEvents } from '../api/client'
import { syncManager } from '../sync/SyncManager'
import { useNavigate } from 'react-router-dom'

export default function Search() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<Array<{ conversation_id: string; seq: number; message_id: string }>>([])
  const nav = useNavigate()

  async function run() {
    if (!q.trim()) return
    setLoading(true)
    try {
      const data = await apiSearch({ q: q.trim(), limit: 50 })
      const withPreview = await Promise.all((data || []).map(async (it) => {
        try {
          const evs = await listEvents(it.conversation_id, { around: it.seq, limit: 1 })
          const content = evs?.[0]?.data?.content || ''
          return { ...it, preview: content }
        } catch { return { ...it } }
      }))
      setResults(withPreview as any)
    } finally {
      setLoading(false)
    }
  }

  async function jump(item: { conversation_id: string; seq: number }) {
    const cid = item.conversation_id
    localStorage.setItem('gp_session_id', cid)
    await syncManager.ensureLoaded(cid)
    await syncManager.jumpToSeq(cid, item.seq)
    nav(`/chat?cid=${encodeURIComponent(cid)}&seq=${item.seq}`)
  }

  return (
    <Card title="搜索">
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="输入关键词，回车搜索" onPressEnter={run} />
        <Button type="primary" loading={loading} onClick={run}>搜索</Button>
      </Space.Compact>
      {results.length === 0 ? (
        <Typography.Text type="secondary">支持按关键字搜索离线消息（服务端 FTS 可用时返回命中）。</Typography.Text>
      ) : (
        <List
          dataSource={results}
          renderItem={(it: any) => (
            <List.Item onClick={() => jump(it)} style={{ cursor: 'pointer' }}>
              <Space direction="vertical" size={2}>
                <Typography.Text>会话: {it.conversation_id}</Typography.Text>
                <Typography.Text type="secondary">定位 seq: {it.seq}</Typography.Text>
                {it.preview && (
                  <Typography.Paragraph ellipsis={{ rows: 2 }}>
                    {highlight(it.preview, q)}
                  </Typography.Paragraph>
                )}
              </Space>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}

function highlight(text: string, q: string) {
  const idx = text.toLowerCase().indexOf(q.toLowerCase())
  if (idx < 0) return text
  const pre = text.slice(0, idx)
  const mid = text.slice(idx, idx + q.length)
  const suf = text.slice(idx + q.length)
  return (
    <span>
      {pre}
      <mark>{mid}</mark>
      {suf}
    </span>
  )
}
