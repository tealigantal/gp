import { useState } from 'react'
import { Card, Input, Button, List, Space, Typography, message } from 'antd'
import { searchHits } from '../api/client'
import { asSearchHits } from '../api/adapters'
import { useNavigate } from 'react-router-dom'
import { setSessionId as persistSessionId } from '../utils/session'

export default function Search() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<ReturnType<typeof asSearchHits>>([])
  const nav = useNavigate()

  async function run() {
    if (!q.trim()) return
    setLoading(true)
    try {
      const data = await searchHits({ q: q.trim(), limit: 50 })
      setResults(asSearchHits(data))
    } catch (e: any) {
      message.error(e?.message || '搜索失败')
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  async function jump(item: { conversation_id: string; seq: number }) {
    const cid = item.conversation_id
    persistSessionId(cid)
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
                    {highlightWithIndices(it.preview, it.highlights || [])}
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

function highlightWithIndices(text: string, highlights: Array<{ start: number; length: number }>) {
  if (!highlights || highlights.length === 0) return text
  const h = highlights[0]
  const start = Math.max(0, h.start)
  const end = Math.min(text.length, start + Math.max(0, h.length))
  const pre = text.slice(0, start)
  const mid = text.slice(start, end)
  const suf = text.slice(end)
  return (
    <span>
      {pre}
      <mark>{mid}</mark>
      {suf}
    </span>
  )
}
