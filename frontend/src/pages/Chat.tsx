import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, Input, List, Space, Spin, Typography } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { chat } from '../api/client'
import type { ChatReq } from '../api/types'
import { useNavigate } from 'react-router-dom'

type Msg = { role: 'user' | 'assistant'; content: string; tool?: any }

const LOCAL_SESSION_KEY = 'gp_session_id'
const LAST_RECOMMEND_RESULT_KEY = 'gp_last_recommend_result'

export default function Chat() {
  const nav = useNavigate()
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(LOCAL_SESSION_KEY))
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (sessionId) localStorage.setItem(LOCAL_SESSION_KEY, sessionId)
  }, [sessionId])

  const m = useMutation({
    mutationFn: async (text: string) => {
      const body: ChatReq = { session_id: sessionId, message: text }
      const resp = await chat(body)
      if (!sessionId && resp.session_id) setSessionId(resp.session_id)
      // persist last recommend if present
      const tool = resp.tool_trace
      if (tool?.triggered_recommend && tool?.recommend_result) {
        localStorage.setItem(LAST_RECOMMEND_RESULT_KEY, JSON.stringify(tool.recommend_result))
      }
      return resp
    },
    onSuccess: (resp, variables) => {
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: variables },
        { role: 'assistant', content: resp.reply, tool: resp.tool_trace }
      ])
      setInput('')
      setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 50)
    }
  })

  const canSend = useMemo(() => input.trim().length > 0 && !m.isPending, [input, m.isPending])

  return (
    <Card title="对话助手">
      <div ref={listRef} style={{ height: 420, overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12 }}>
        {messages.length === 0 && <Typography.Text type="secondary">试着说：“给我推荐3只低位放量”</Typography.Text>}
        <List
          dataSource={messages}
          renderItem={(msg, idx) => (
            <List.Item key={idx} style={{ display: 'block' }}>
              <Typography.Paragraph strong>{msg.role === 'user' ? '你' : '助手'}</Typography.Paragraph>
              <Typography.Paragraph style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</Typography.Paragraph>
              {msg.role === 'assistant' && msg.tool?.triggered_recommend && (
                <Space>
                  <Alert type="success" message="已生成一次推荐" showIcon />
                  <Button
                    type="link"
                    onClick={() => {
                      // Prefer refreshing data on /recommend page; but we keep last result for quick view if needed
                      nav('/recommend')
                    }}
                  >
                    查看本次推荐
                  </Button>
                </Space>
              )}
            </List.Item>
          )}
        />
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入消息..." />
        <Button type="primary" disabled={!canSend} onClick={() => m.mutate(input)}>
          {m.isPending ? <Spin /> : '发送'}
        </Button>
      </Space.Compact>
      {m.isError && <Alert type="error" style={{ marginTop: 12 }} message={(m.error as any)?.message || '发送失败'} />}
    </Card>
  )
}

