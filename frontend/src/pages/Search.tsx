import { useState } from 'react'
import { Card, Input, Button, List, Space, Typography, message } from 'antd'
import { searchHits } from '../api/client'
import { asSearchHits } from '../api/adapters'
import { renderHighlight } from '../utils/highlight'
import type { SearchHit } from '../api/contracts'
import { useNavigate } from 'react-router-dom'
import { setSessionId as persistSessionId } from '../utils/session'

export default function Search() {
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<SearchHit[]>([])
  const nav = useNavigate()

  async function run() {
    if (!q.trim()) return
    setLoading(true)
    try {
      const data = await searchHits({ q: q.trim(), limit: 50 })
      setResults(asSearchHits(data))
    } catch (e: unknown) {
      const err = e as { message?: string }
      message.error(err?.message || '搜索失败')
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
          renderItem={(it: SearchHit) => (
            <List.Item onClick={() => jump(it)} style={{ cursor: 'pointer' }}>
              <Space direction="vertical" size={2}>
                <Typography.Text>会话: {it.conversation_id}</Typography.Text>
                <Typography.Text type="secondary">定位 seq: {it.seq}</Typography.Text>
                {it.preview && (
                  <Typography.Paragraph ellipsis={{ rows: 2 }}>
                    {renderHighlight(it.preview, it.highlights || [])}
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
