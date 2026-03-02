import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, FloatButton, Input, List, Space, Spin, Typography, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { chat } from '../api/client'
import type { ChatReq } from '../api/types'
import { useLocation } from 'react-router-dom'
import { syncManager } from '../sync/SyncManager'
import MessageBubble from '../components/MessageBubble'
import RecommendationCard from '../components/RecommendationCard'
import KlineCard from '../components/KlineCard'
import WorkbenchLayout from '../components/WorkbenchLayout'
import ToolsPanel from '../components/ToolsPanel'
import { getRiskProfile } from '../store/settings'
import { getOrCreateSessionId, setSessionId as persistSessionId } from '../utils/session'
import { useConversationEvents } from '../hooks/useConversationEvents'

type Msg = { role: 'user' | 'assistant'; content?: string; kind?: 'text'|'rec'|'kline'; payload?: any }

const LAST_RECOMMEND_RESULT_KEY = 'gp_last_recommend_result'

export default function Chat() {
  const loc = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const listRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [hasNew, setHasNew] = useState(false)
  const lastMaxSeqRef = useRef<number>(0)
  const sessionIdRef = useRef<string | null>(sessionId)

  useEffect(() => {
    if (sessionId) persistSessionId(sessionId)
    sessionIdRef.current = sessionId
    syncManager.currentConversationId = () => sessionId
  }, [sessionId])

  useEffect(() => {
    const sid = getOrCreateSessionId()
    setSessionId(sid)
  }, [])

  // 订阅：事件变化驱动渲染（加载与轮询由 hook 负责）
  useEffect(() => {
    if (!sessionId) return
    const unsub = syncManager.subscribe(() => renderFromEvents())
    return () => unsub()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // 增量拉取 events（2.5s；cursor 持久化）
  useConversationEvents(sessionId)

  // 前台可见性切换时触发轻量同步
  useEffect(() => {
    const onVis = () => { if (!document.hidden) syncManager.requestSync('visibility_change') }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  // 支持：?cid=xxx&seq=123 定位
  useEffect(() => {
    const params = new URLSearchParams(loc.search)
    const cid = params.get('cid') || undefined
    const seqStr = params.get('seq') || undefined
    if (cid) {
      if (cid !== sessionId) {
        setSessionId(cid)
        persistSessionId(cid)
      }
      const seq = seqStr ? Number(seqStr) : undefined
      if (seq && Number.isFinite(seq)) {
        syncManager.jumpToSeq(cid, seq).then(() => renderFromEvents())
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.search])

  function renderFromEvents(cidArg?: string | null) {
    const cid = cidArg || sessionId
    if (!cid) return
    const evs = syncManager.messages(cid)
    const view: Msg[] = []
    for (const e of evs) {
      const role: 'user' | 'assistant' = (e.actor_id === 'user' ? 'user' : 'assistant')
      if (e?.data?.kind === 'card') {
        const p = e?.data?.payload || {}
        if (p?.type === 'recommendation' && Array.isArray(p?.picks)) {
          view.push({ role, kind: 'rec', payload: p })
          continue
        }
        if (p?.type === 'kline' && p?.symbol) {
          view.push({ role, kind: 'kline', payload: p })
          continue
        }
        if (p?.type === 'status') continue
      }
      view.push({ role, kind: 'text', content: e?.data?.content || '' })
    }
    setMessages(view)
    const maxSeq = evs.length ? evs[evs.length - 1].seq : 0
    if (maxSeq && cid) syncManager.reportRead(cid, maxSeq)
    if (maxSeq > lastMaxSeqRef.current && !atBottom) setHasNew(true)
    lastMaxSeqRef.current = Math.max(lastMaxSeqRef.current, maxSeq)
  }

  const m = useMutation({
    mutationFn: async ({ text, msgId }: { text: string; msgId?: string }) => {
      const body: ChatReq = { session_id: sessionIdRef.current, message: text, message_id: msgId }
      const resp = await chat(body)
      if (!sessionId && resp.session_id) setSessionId(resp.session_id)
      const tool = resp.tool_trace
      if (tool?.triggered_recommend && tool?.recommend_result) {
        localStorage.setItem(LAST_RECOMMEND_RESULT_KEY, JSON.stringify(tool.recommend_result))
      }
      return resp
    },
    onSuccess: async (resp) => {
      const cid = resp?.session_id || sessionIdRef.current
      if (cid) {
        // Immediately inject assistant reply as a local event for smooth UX
        try {
          const id = resp?.assistant_message_id
          if (id) {
            const pseudoSeq = syncManager.maxSeq(String(cid)) + 1
            const ev = {
              id,
              conversation_id: String(cid),
              seq: pseudoSeq,
              type: 'message.created',
              actor_id: 'assistant',
              created_at: new Date().toISOString(),
              data: { message_id: id, kind: 'text', content: resp.reply }
            } as any
            syncManager.mergeEvents(String(cid), [ev])
          }
        } catch { /* ignore */ }
        // Then ensure we pull any missing increments
        try { await syncManager.ensureLoaded(String(cid)) } catch {}
        syncManager.requestSync('chat_success')
        renderFromEvents(String(cid))
      }
    },
    onError: (err: any) => {
      message.error(err?.message || '发送失败')
    }
  })

  const canSend = useMemo(() => input.trim().length > 0 && !m.isPending, [input, m.isPending])

  async function ensureCid() {
    let cid = sessionId || null
    if (!cid) {
      cid = 'sess-' + Date.now()
      setSessionId(cid)
      persistSessionId(cid)
    }
    sessionIdRef.current = cid
    return cid
  }

  async function insertKlineCards(symbols: string[]) {
    const cid = await ensureCid()
    for (const s of symbols) {
      syncManager.pushOutbox({
        conversation_id: cid,
        type: 'message.created',
        actor_id: 'assistant',
        data: { message_id: 'card-kline-' + Date.now(), kind: 'card', content: 'kline', payload: { type: 'kline', symbol: s } }
      })
    }
    syncManager.requestSync('kline_cards')
    renderFromEvents(cid)
  }

  async function handleSubmit(raw: string) {
    const text = raw.trim()
    if (!text) return
    const cid = await ensureCid()
    // 简化：默认走 LLM 对话通道
    if (atBottom) setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 30)
    // 清空输入，避免按下回车后文本残留
    setInput('')
    // Local optimistic injection for user message (do not write to outbox)
    const msgId = 'msg-' + Date.now()
    try {
      const pseudoSeq = syncManager.maxSeq(cid) + 1
      syncManager.mergeEvents(cid, [{
        id: msgId,
        conversation_id: cid,
        seq: pseudoSeq,
        type: 'message.created',
        actor_id: 'user',
        created_at: new Date().toISOString(),
        data: { message_id: msgId, kind: 'text', content: text }
      } as any])
      renderFromEvents(cid)
    } catch { /* ignore */ }
    m.mutate({ text, msgId })
  }

  const left = (
    <div>
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40
          setAtBottom(nearBottom)
        }}
        style={{ height: 420, overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12, borderRadius: 8 }}
      >
        {messages.length === 0 && <Typography.Text type="secondary">示例：给我推荐3只低估值</Typography.Text>}
        <List dataSource={messages} renderItem={(msg, idx) => (
          <List.Item key={idx} style={{ display: 'block', border: 'none', padding: 0 }}>
            {msg.kind === 'rec' && msg.payload?.picks ? (
              <RecommendationCard picks={msg.payload.picks} meta={msg.payload?.meta} onShowKline={async (sym) => { if(!sessionId) return; syncManager.pushOutbox({ conversation_id: sessionId, type: 'message.created', actor_id: 'assistant', data: { message_id: 'card-kline-' + Date.now(), kind: 'card', content: 'kline', payload: { type: 'kline', symbol: sym } } }); syncManager.requestSync('kline_card'); renderFromEvents(sessionId) }} />
            ) : msg.kind === 'kline' && msg.payload?.symbol ? (
              <KlineCard symbol={msg.payload.symbol} conversationId={sessionId} />
            ) : (
              <MessageBubble role={msg.role} content={msg.content || ''} />
            )}
          </List.Item>
        )} />
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="对话指令：如 给我推荐3只低估值 / 查询 600519 K线 / 查看进度"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              const ne: any = e
              if (ne?.nativeEvent?.isComposing) return
              e.preventDefault()
              if (canSend) handleSubmit(input)
            }
          }}
        />
        {m.isPending && <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px' }}><Spin /></div>}
      </Space.Compact>
      {!atBottom && (
        <>
          {hasNew && (
            <div
              onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }}
              style={{ cursor: 'pointer', color: '#1677ff', textAlign: 'center', margin: '6px 0' }}
            >有新内容，点击查看</div>
          )}
          <FloatButton shape="square" type="primary" tooltip="回到底部" style={{ right: 24, bottom: 24 }} onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }} />
        </>
      )}
    </div>
  )

  const right = (
    <ToolsPanel
      conversationId={sessionId}
      onEnsureConversation={(cid) => { setSessionId(cid); persistSessionId(cid) }}
      onRefresh={() => { syncManager.requestSync('tools_refresh'); setTimeout(()=>renderFromEvents(),50) }}
    />
  )

  return (
    <Card title="对话">
      <WorkbenchLayout left={left} right={right} />
    </Card>
  )
}
