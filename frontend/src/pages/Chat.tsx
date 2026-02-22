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
import { parseIntent } from '../intent/parser'
import { getRiskProfile } from '../store/settings'

type Msg = { role: 'user' | 'assistant'; content?: string; tool?: any; kind?: 'text'|'rec'|'kline'; payload?: any }

const LOCAL_SESSION_KEY = 'gp_session_id'
const LAST_RECOMMEND_RESULT_KEY = 'gp_last_recommend_result'

export default function Chat() {
  const loc = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(() => localStorage.getItem(LOCAL_SESSION_KEY))
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Msg[]>([])
  const listRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [hasNew, setHasNew] = useState(false)
  const lastMaxSeqRef = useRef<number>(0)
  const sessionIdRef = useRef<string | null>(sessionId)
  // state for scroll + messages only; using events as source of truth

  useEffect(() => {
    if (sessionId) localStorage.setItem(LOCAL_SESSION_KEY, sessionId)
    sessionIdRef.current = sessionId
  }, [sessionId])

  // 鍚屾锛氳嫢宸叉湁浼氳瘽锛屽姞杞戒簨浠跺巻鍙插苟淇濇寔杞
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

  // 前台切换立即同步
  useEffect(() => {
    const onVis = () => { if (!document.hidden) syncManager.flush().catch(()=>undefined) }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  // 鏀寔鎼滅储缁撴灉璺宠浆锛?chat?cid=xxx&seq=123
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
        if (p?.type === 'status') {
          // status 卡片仅在右侧进度面板展示，左侧对话隐藏
          continue
        }
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
      // persist last recommend if present
      const tool = resp.tool_trace
      if (tool?.triggered_recommend && tool?.recommend_result) {
        localStorage.setItem(LAST_RECOMMEND_RESULT_KEY, JSON.stringify(tool.recommend_result))
      }
      return resp
    },
    onSuccess: async (resp) => {
      // 统一：确保加载 + 立即增量同步 + 重绘
      const cid = resp?.session_id || sessionIdRef.current
      if (cid) {
        try { await syncManager.ensureLoaded(String(cid)) } catch { /* ignore */ }
        try { await syncManager.flush() } catch { /* ignore */ }
        // 仅“等待-拉取”，不做任何兜底写入。保持后端为唯一事实来源。
        const targetId = resp.assistant_message_id
        const start = Date.now()
        const waitMs = 1600
        if (targetId) {
          while (Date.now() - start < waitMs) {
            const evs = syncManager.messages(String(cid))
            if (evs.some((e) => e.id === targetId)) break
            try { await new Promise((r) => setTimeout(r, 150)) } catch {}
            try { await syncManager.flush() } catch { /* ignore */ }
          }
        } else {
          // 没有返回 id，也做一次轻量拉取
          try { await new Promise((r) => setTimeout(r, 150)) } catch {}
          try { await syncManager.flush() } catch { /* ignore */ }
        }
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
      localStorage.setItem(LOCAL_SESSION_KEY, cid)
    }
    sessionIdRef.current = cid
    return cid
  }

  function pushStatus(cid: string, code: string, text: string, runId?: number) {
    syncManager.pushOutbox({
      conversation_id: cid,
      type: 'message.created',
      actor_id: 'assistant',
      data: { message_id: 'status-' + code + '-' + Date.now(), kind: 'card', content: 'status', payload: { type: 'status', code, text, run_id: runId, ts: Date.now() } }
    })
  }

  async function triggerRecommend(slots: { topk?: number; universe?: 'auto' | 'symbols'; symbols?: string[]; risk?: string }, ctx?: { cid?: string; msgId?: string; rawText?: string }) {
    let cid: string | null = ctx?.cid || null
    const msgId = ctx?.msgId
    const runId = Date.now()
    try {
      cid = cid || await ensureCid()
      const topk = slots.topk ?? 3
      const risk = (slots.risk as any) || getRiskProfile() || 'normal'
      const universe = slots.universe || (slots.symbols && slots.symbols.length > 0 ? 'symbols' : 'auto')
      const symTxt = (slots.symbols && slots.symbols.length) ? ` 代码: ${slots.symbols.join(' ')}` : ''
      const text = `推荐 ${topk} 只；风险 ${risk}；范围 ${universe}.${symTxt}`
      // 进度：开始
      pushStatus(cid, 'report_started', '开始生成推荐', runId)
      await syncManager.flush().catch(()=>undefined)
      // 调用后端 /chat，让后端完成推荐、写入最新推荐与卡片（保持会话可追问）
      await chat({ session_id: cid, message: `荐股 ${text}`, message_id: msgId })
      await syncManager.flush().catch(()=>undefined)
      // 进度：完成
      pushStatus(cid, 'plan_complete', '推荐已生成', runId)
      pushStatus(cid, 'complete', '完成', runId)
      await syncManager.flush().catch(()=>undefined)
      renderFromEvents(cid)
    } catch (e: any) {
      message.error(e?.message || '推荐失败')
      if (cid) {
        pushStatus(cid, 'error', '数据不可用或外部源报错', runId)
        pushStatus(cid, 'complete', '完成', runId)
        await syncManager.flush().catch(()=>undefined)
        renderFromEvents(cid)
      }
    }
  }

  async function insertKlineCards(symbols: string[]) {
    const cid = await ensureCid()
    for (const s of symbols) {
      syncManager.pushOutbox({
        conversation_id: cid,
        type: 'message.created',
        actor_id: 'assistant',
        data: { message_id: 'card-kline-' + Date.now() + '-' + s, kind: 'card', content: 'kline', payload: { type: 'kline', symbol: s } }
      })
    }
    await syncManager.flush()
    renderFromEvents()
  }

  async function replyText(text: string) {
    const cid = await ensureCid()
    syncManager.pushOutbox({ conversation_id: cid, type: 'message.created', actor_id: 'assistant', data: { message_id: 'msg-' + Date.now(), kind: 'text', content: text } })
    await syncManager.flush()
    renderFromEvents()
  }

  async function handleSubmit(raw: string) {
    const text = raw.trim()
    if (!text) return
    // 简单：回车即清空输入
    setInput('')
    if (atBottom) setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 0)
    // 幂等双写：无论何种意图，先把原始用户文本写为事件（保证“我说的话”一定显示），/api/chat 传同一个 message_id
    const cid = await ensureCid()
    const msgId = 'msg-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    syncManager.pushOutbox({
      id: msgId,
      conversation_id: cid,
      type: 'message.created',
      actor_id: 'user',
      data: { message_id: msgId, kind: 'text', content: text }
    })
    try { await syncManager.flush() } catch { /* ignore */ }

    const intent = parseIntent(text)
    if (intent.type === 'recommend') {
      await triggerRecommend({ topk: intent.topk, universe: intent.universe, symbols: intent.symbols, risk: intent.risk }, { cid, msgId, rawText: text })
      return
    }
    if (intent.type === 'kline') {
      await insertKlineCards(intent.symbols)
      return
    }
    if (intent.type === 'themes') {
      // summarize from last recommendation card
      const evs = syncManager.messages(cid)
      let themes: any[] = []
      for (let i = evs.length - 1; i >= 0; i--) {
        const e: any = evs[i]
        if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
          const th = e?.data?.payload?.meta?.themes
          if (Array.isArray(th)) { themes = th; break }
        }
      }
      if (!themes.length) {
        await replyText('暂无数据（先生成一次推荐）')
      } else {
        const text = '主题热度：' + themes.slice(0, 10).map((t: any) => `${t?.name || '主题'}${t?.strength != null ? `(${t.strength})` : ''}`).join('、')
        await replyText(text)
      }
      return
    }
    if (intent.type === 'progress') {
      const evs = syncManager.messages(cid)
      const sts = evs.filter((e: any) => e?.data?.kind === 'card' && e?.data?.payload?.type === 'status').map((e: any) => e?.data?.payload)
      if (!sts.length) {
        await replyText('当前无任务')
      } else {
        const groups = new Map<number, any[]>()
        for (const s of sts) { const run = Number(s.run_id || 0) || 0; if (!groups.has(run)) groups.set(run, []); groups.get(run)!.push(s) }
        const runs = Array.from(groups.keys()).sort((a, b) => a - b)
        const latest = groups.get(runs[runs.length - 1]) || []
        const codeSet = new Set(latest.map((s) => String(s.code)))
        const order = ['report_started', 'planning', 'plan_complete', 'complete']
        const current = order.find((c) => !codeSet.has(c)) || 'complete'
        await replyText(current === 'complete' ? '当前无任务' : `进度：${labelOf(current)}`)
      }
      return
    }
    // default: send to LLM chat（用户原始文本已写入事件，用同一 message_id 调后端）
    if (atBottom) setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 30)
    m.mutate({ text, msgId })
  }

  const left = (
    <div><div
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
            {msg.kind === 'rec' && msg.payload?.picks ? (
              <RecommendationCard picks={msg.payload.picks} onShowKline={async (sym) => { if(!sessionId) return; syncManager.pushOutbox({ conversation_id: sessionId, type: 'message.created', actor_id: 'assistant', data: { message_id: 'card-kline-' + Date.now(), kind: 'card', content: 'kline', payload: { type: 'kline', symbol: sym } } }); await syncManager.flush(); renderFromEvents(sessionId) }} />
            ) : msg.kind === 'kline' && msg.payload?.symbol ? (
              <KlineCard symbol={msg.payload.symbol} />
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
          placeholder="对话即指令：如 ‘给我推荐3只低估值’ / ‘看看600519 K线’ / ‘现在进度到哪了’"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              const ne: any = e
              if (ne?.nativeEvent?.isComposing) return // IME composing
              e.preventDefault()
              if (canSend) handleSubmit(input)
            }
          }}
        />
        {m.isPending && <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px' }}><Spin /></div>}
      </Space.Compact>
      {/* error area intentionally minimal，避免多余提示影响流畅度 */}
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
      onEnsureConversation={(cid) => { setSessionId(cid); localStorage.setItem(LOCAL_SESSION_KEY, cid) }}
      onRefresh={() => { syncManager.flush().catch(()=>undefined).then(()=>renderFromEvents()) }}
    />
  )

  return (
    <Card title="对话助手">
      <WorkbenchLayout left={left} right={right} />
    </Card>
  )
}

function labelOf(code: string) {
  switch (code) {
    case 'report_started': return '开始';
    case 'planning': return '生成参数与候选';
    case 'plan_complete': return '结果生成';
    case 'complete': return '完成';
    default: return code;
  }
}










