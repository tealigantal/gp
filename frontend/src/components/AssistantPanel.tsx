import { useEffect, useState } from 'react'
import { Button, Card, Input, List, Space, Spin, Typography, message } from 'antd'
import { chat } from '../api/client'
import { getOrCreateSessionId, setSessionId as persistSessionId } from '../utils/session'

type Msg = { role: 'user' | 'assistant'; content: string }

export default function AssistantPanel({ onMessageSent }: { onMessageSent?: () => void }) {
  const [sessionId, setSid] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [pending, setPending] = useState(false)
  const [msgs, setMsgs] = useState<Msg[]>([])

  useEffect(() => { setSid(getOrCreateSessionId()) }, [])

  async function send() {
    const text = input.trim()
    if (!text || pending) return
    setMsgs((m) => [...m, { role: 'user', content: text }])
    setInput(''); setPending(true)
    try {
      const resp = await chat({ session_id: sessionId || undefined, message: text })
      if (resp?.session_id && resp.session_id !== sessionId) { setSid(resp.session_id); persistSessionId(resp.session_id) }
      setMsgs((m) => [...m, { role: 'assistant', content: resp.reply || '' }])
      onMessageSent?.()
    } catch (e: any) {
      message.error(e?.message || '发送失败')
    } finally {
      setPending(false)
    }
  }

  return (
    <Card size="small" title="LLM 助手">
      <List
        size="small"
        dataSource={msgs.slice(-6)}
        renderItem={(m, idx) => (
          <List.Item key={idx} style={{ border: 'none', padding: '4px 0' }}>
            <Typography.Text type={m.role === 'user' ? undefined : 'secondary'}>
              {m.role === 'user' ? '你: ' : '助手: '}{m.content}
            </Typography.Text>
          </List.Item>
        )}
      />
      <Space.Compact style={{ width: '100%', marginTop: 8 }}>
        <Input.TextArea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder="问：今天有什么票，为什么排第一？" onPressEnter={(e) => { if (!e.shiftKey) { e.preventDefault(); send() } }} />
        <Button type="primary" onClick={send} disabled={pending}>发送</Button>
        {pending && <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px' }}><Spin /></div>}
      </Space.Compact>
    </Card>
  )
}
