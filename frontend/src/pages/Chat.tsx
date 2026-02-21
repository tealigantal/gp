import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Card, FloatButton, Input, List, Space, Spin, Typography } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { chat } from '../api/client'
import type { ChatReq } from '../api/types'
import { useLocation, useNavigate } from 'react-router-dom'
import { syncManager } from '../sync/SyncManager'
import MessageBubble from '../components/MessageBubble'

type Msg = { role: 'user' | 'assistant'; content: string; tool?: any }

const LOCAL_SESSION_KEY = 'gp_session_id'
const LAST_RECOMMEND_RESULT_KEY = 'gp_last_recommend_result'

export default function Chat() {
  const nav = useNavigate()
  const loc = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(LOCAL_SESSION_KEY))
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const listRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)

  useEffect(() => {
    if (sessionId) localStorage.setItem(LOCAL_SESSION_KEY, sessionId)
  }, [sessionId])

  // 同步：若已有会话，加载事件历史并保持轮询
  useEffect(() => {
    if (!sessionId) return
    let unsub = () => {}
    ;(async () => {
      await syncManager.ensureLoaded(sessionId)
      renderFromEvents()
      unsub = syncManager.subscribe(() => renderFromEvents())
      syncManager.start()
    })()
    return () => unsub()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // 支持搜索结果跳转：/chat?cid=xxx&seq=123
  useEffect(() => {
    const params = new URLSearchParams(loc.search)
    const cid = params.get('cid') || undefined
    const seqStr = params.get('seq') || undefined
    if (cid) {
      if (cid !== sessionId) {
        setSessionId(cid)
        localStorage.setItem(LOCAL_SESSION_KEY, cid)
      }
      const seq = seqStr ? Number(seqStr) : undefined
      if (seq && Number.isFinite(seq)) {
        syncManager.jumpToSeq(cid, seq).then(() => renderFromEvents())
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.search])

  function renderFromEvents() {
    if (!sessionId) return
    const evs = syncManager.messages(sessionId)
    const view: Msg[] = evs.map((e) => ({ role: (e.actor_id === 'user' ? 'user' : 'assistant'), content: e.data?.content || '' }))
    setMessages(view)
    const maxSeq = evs.length ? evs[evs.length - 1].seq : 0
    if (maxSeq) syncManager.reportRead(sessionId, maxSeq)
  }

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
    onSuccess: async (_resp, variables) => {
      setMessages((prev) => [...prev, { role: 'user', content: variables }])
      setInput('')
      setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 30)
      await syncManager.flush().catch(() => undefined)
      renderFromEvents()
    }
  })

  const canSend = useMemo(() => input.trim().length > 0 && !m.isPending, [input, m.isPending])

  return (
    <Card title="对话助手">
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40
          setAtBottom(nearBottom)
        }}
        style={{ height: 420, overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12, borderRadius: 8 }}
      >
        {messages.length === 0 && <Typography.Text type="secondary">试输入：“给我推荐3只低估值”</Typography.Text>}
        <List dataSource={messages} renderItem={(msg, idx) => (
          <List.Item key={idx} style={{ display: 'block', border: 'none', padding: 0 }}>
            <MessageBubble role={msg.role} content={msg.content} />
            {msg.role === 'assistant' && msg.tool?.triggered_recommend && (
              <Space style={{ margin: '4px 8px' }}>
                <Alert type="success" message="已生成一轮推荐" showIcon />
                <Button type="link" onClick={() => nav('/recommend')}>查看本次推荐</Button>
              </Space>
            )}
          </List.Item>
        )} />
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea rows={2} value={input} onChange={(e) => setInput(e.target.value)} placeholder="输入消息..." />
        <Button type="primary" disabled={!canSend} onClick={() => m.mutate(input)}>
          {m.isPending ? <Spin /> : '发送'}
        </Button>
      </Space.Compact>
      {m.isError && <Alert type="error" style={{ marginTop: 12 }} message={(m.error as any)?.message || '发送失败'} />}
      {!atBottom && (
        <FloatButton shape="square" type="primary" tooltip="回到底部" style={{ right: 24, bottom: 24 }} onClick={() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' })} />
      )}
    </Card>
  )
}
