import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, FloatButton, Input, List, Space, Spin, Typography, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { chat } from '../api/client'
import type { ChatReq } from '../api/types'
import { useLocation } from 'react-router-dom'
import { syncManager } from '../sync/SyncManager'
import MessageBubble from '../components/MessageBubble'
import RecommendationCard from '../components/RecommendationCard'
import DataStatusBar from '../components/DataStatusBar'
import KlineCard from '../components/KlineCard'
import WorkbenchLayout from '../components/WorkbenchLayout'
import ToolsPanel from '../components/ToolsPanel'
import { parseIntent } from '../intent/parser'
import { getRiskProfile } from '../store/settings'
import { getOrCreateSessionId, setSessionId as persistSessionId } from '../utils/session'
import { useConversationEvents } from '../hooks/useConversationEvents'

type Msg = { role: 'user' | 'assistant'; content?: string; tool?: any; kind?: 'text'|'rec'|'kline'; payload?: any }

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
  // state for scroll + messages only; using events as source of truth

  useEffect(() => {
    if (sessionId) persistSessionId(sessionId)
    sessionIdRef.current = sessionId
    // expose to consumers like DataStatusBar without tight coupling
    syncManager.currentConversationId = () => sessionId
  }, [sessionId])

  // initialize session id from URL/localStorage or create one
  useEffect(() => {
    const sid = getOrCreateSessionId()
    setSessionId(sid)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 同步：若已有会话，加载事件历史并保持轮询
  useEffect(() => {
    if (!sessionId) return
    let unsub = () => {}
    ;(async () => {
            unsub = syncManager.subscribe(() => renderFromEvents())
    })()
    return () => unsub()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // incremental events polling (2.5s; persists cursor)
  useConversationEvents(sessionId)

  // ǰ̨�л�����ͬ��
  useEffect(() => {
    const onVis = () => { if (!document.hidden) syncManager.requestSync('visibility_change') }
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  // 支持搜索结果跳转�?chat?cid=xxx&seq=123
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
        if (p?.type === 'status') {
          // status ��Ƭ�����Ҳ�������չʾ�����Ի�����
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
      // ͳһ��ȷ������ + ��������ͬ�� + �ػ�
      const cid = resp?.session_id || sessionIdRef.current
      if (cid) {
        try { await syncManager.ensureLoaded(String(cid)) } catch { /* ignore */ }
        try { syncManager.requestSync('manual') } catch { /* ignore */ }
        // �����ȴ�-��ȡ���������κζ���д�롣���ֺ��ΪΨһ��ʵ��Դ��
        const targetId = resp.assistant_message_id
        const start = Date.now()
        const waitMs = 1600
        if (targetId) {
          while (Date.now() - start < waitMs) {
            const evs = syncManager.messages(String(cid))
            if (evs.some((e) => e.id === targetId)) break
            try { await new Promise((r) => setTimeout(r, 150)) } catch {}
            try { syncManager.requestSync('manual') } catch { /* ignore */ }
          }
        } else {
          // û�з��� id��Ҳ��һ��������ȡ
          try { await new Promise((r) => setTimeout(r, 150)) } catch {}
          try { syncManager.requestSync('manual') } catch { /* ignore */ }
        }
        renderFromEvents(String(cid))
      }
    },
    onError: (err: any) => {
      message.error(err?.message || '����ʧ��')
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
      const symTxt = (slots.symbols && slots.symbols.length) ? ` ����: ${slots.symbols.join(' ')}` : ''
      const text = `�Ƽ� ${topk} ֻ������ ${risk}����Χ ${universe}.${symTxt}`
      // ���ȣ���ʼ
      pushStatus(cid, 'report_started', '��ʼ�����Ƽ�', runId)
      // ���ȣ��滮/��ѡ�׶Σ�ǰ�˿ɼ��м�̬��
      pushStatus(cid, 'planning', '���ɲ������ѡ', runId)
      syncManager.requestSync('manual')
      // ���ú�� /chat���ú������Ƽ���д�������Ƽ��뿨Ƭ�����ֻỰ��׷�ʣ�
      await chat({ session_id: cid, message: `���� ${text}`, message_id: msgId })
      syncManager.requestSync('manual')
      // ���ȣ����
      pushStatus(cid, 'plan_complete', '�Ƽ�������', runId)
      pushStatus(cid, 'complete', '���', runId)
      syncManager.requestSync('manual')
      renderFromEvents(cid)
    } catch (e: any) {
      message.error(e?.message || '�Ƽ�ʧ��')
      if (cid) {
        pushStatus(cid, 'error', '���ݲ����û��ⲿԴ����', runId)
        pushStatus(cid, 'complete', '���', runId)
        syncManager.requestSync('manual')
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
    syncManager.requestSync('manual')
    renderFromEvents()
  }

  async function replyText(text: string) {
    const cid = await ensureCid()
    syncManager.pushOutbox({ conversation_id: cid, type: 'message.created', actor_id: 'assistant', data: { message_id: 'msg-' + Date.now(), kind: 'text', content: text } })
    syncManager.requestSync('manual')
    renderFromEvents()
  }

  async function handleSubmit(raw: string) {
    const text = raw.trim()
    if (!text) return
    // �򵥣��س����������
    setInput('')
    if (atBottom) setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 0)
    // �ݵ�˫д�����ۺ�����ͼ���Ȱ�ԭʼ�û��ı�дΪ�¼�����֤����˵�Ļ���һ����ʾ����/api/chat ��ͬһ�� message_id
    const cid = await ensureCid()
    const msgId = 'msg-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
    syncManager.pushOutbox({
      id: msgId,
      conversation_id: cid,
      type: 'message.created',
      actor_id: 'user',
      data: { message_id: msgId, kind: 'text', content: text }
    })
    try { syncManager.requestSync('manual') } catch { /* ignore */ }

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
        await replyText('�������ݣ�������һ���Ƽ���')
      } else {
        const text = '�����ȶȣ�' + themes.slice(0, 10).map((t: any) => {
          const s = String(t?.strength || '').trim()
          return `${t?.name || '����'}${s ? `(${s})` : ''}`
        }).join('��')
        await replyText(text)
      }
      return
    }
    if (intent.type === 'progress') {
      const evs = syncManager.messages(cid)
      const sts = evs.filter((e: any) => e?.data?.kind === 'card' && e?.data?.payload?.type === 'status').map((e: any) => e?.data?.payload)
      if (!sts.length) {
        await replyText('��ǰ������')
      } else {
        const groups = new Map<number, any[]>()
        for (const s of sts) { const run = Number(s.run_id || 0) || 0; if (!groups.has(run)) groups.set(run, []); groups.get(run)!.push(s) }
        const runs = Array.from(groups.keys()).sort((a, b) => a - b)
        const latest = groups.get(runs[runs.length - 1]) || []
        const codeSet = new Set(latest.map((s) => String(s.code)))
        const order = ['report_started', 'planning', 'plan_complete', 'complete']
        const current = order.find((c) => !codeSet.has(c)) || 'complete'
        await replyText(current === 'complete' ? '��ǰ������' : `���ȣ�${labelOf(current)}`)
      }
      return
    }
    // default: send to LLM chat���û�ԭʼ�ı���д���¼�����ͬһ message_id ����ˣ�
    if (atBottom) setTimeout(() => listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }), 30)
    m.mutate({ text, msgId })
  }

  const left = (
    <div>
      <DataStatusBar />
      <div
          ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40
          setAtBottom(nearBottom)
        }}
        style={{ height: 420, overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12, borderRadius: 8 }}
      >
        {messages.length === 0 && <Typography.Text type="secondary">�����룺�������Ƽ�3ֻ�͹�ֵ��</Typography.Text>}
        <List dataSource={messages} renderItem={(msg, idx) => (
          <List.Item key={idx} style={{ display: 'block', border: 'none', padding: 0 }}>
            {msg.kind === 'rec' && msg.payload?.picks ? (
              <RecommendationCard picks={msg.payload.picks} meta={msg.payload?.meta} onShowKline={async (sym) => { if(!sessionId) return; syncManager.pushOutbox({ conversation_id: sessionId, type: 'message.created', actor_id: 'assistant', data: { message_id: 'card-kline-' + Date.now(), kind: 'card', content: 'kline', payload: { type: 'kline', symbol: sym } } }); syncManager.requestSync('manual'); renderFromEvents(sessionId) }} />
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
          placeholder="�Ի���ָ��� �������Ƽ�3ֻ�͹�ֵ�� / ������600519 K�ߡ� / �����ڽ��ȵ����ˡ�"
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
      {/* error area intentionally minimal�����������ʾӰ�������� */}
      {!atBottom && (
        <>
          {hasNew && (
            <div
              onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }}
              style={{ cursor: 'pointer', color: '#1677ff', textAlign: 'center', margin: '6px 0' }}
            >�������ݣ�����鿴</div>
          )}
          <FloatButton shape="square" type="primary" tooltip="�ص��ײ�" style={{ right: 24, bottom: 24 }} onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }} />
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
    <Card title="�Ի�����">
      <WorkbenchLayout left={left} right={right} />
    </Card>
  )
}

function labelOf(code: string) {
  switch (code) {
    case 'report_started': return '��ʼ';
    case 'planning': return '���ɲ������ѡ';
    case 'plan_complete': return '�������';
    case 'complete': return '���';
    default: return code;
  }
}










