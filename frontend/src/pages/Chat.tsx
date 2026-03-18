import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, FloatButton, Input, List, Space, Spin, Typography, message } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import MessageBubble from '../components/MessageBubble'
import RecommendationDetail from '../features/recommendation/RecommendationDetail'
import WorkbenchLayout from '../components/WorkbenchLayout'
import ToolsPanel from '../components/ToolsPanel'
import Conversations from './Conversations'
import KlineInspector from '../features/artifacts/KlineInspector'
import { setSessionId as persistSessionId } from '../utils/session'
import { useConversationThread } from '../features/thread/useConversationThread'
import { useSendMessage } from '../features/thread/useSendMessage'
import { chat as chatApi, getRecommendationArtifact } from '../api/client'
import { asRecommendationArtifact } from '../api/adapters'
import { useSelectedArtifact } from '../features/artifacts/useSelectedArtifact'
import { getOrCreateSessionId } from '../utils/session'
import type { ThreadItem, RecommendationArtifact } from '../api/contracts'

export default function Chat() {
  const nav = useNavigate()
  const loc = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [pendingTexts, setPendingTexts] = useState<string[]>([])
  const listRef = useRef<HTMLDivElement>(null)
  const [atBottom, setAtBottom] = useState(true)
  const [hasNew, setHasNew] = useState(false)

  const params = useMemo(() => new URLSearchParams(loc.search), [loc.search])
  const cidParam = params.get('cid') || null
  const seqParam = params.get('seq')
  const anchorSeq = seqParam ? Number(seqParam) : undefined

  useEffect(() => {
    if (cidParam && cidParam !== sessionId) {
      setSessionId(cidParam)
      persistSessionId(cidParam)
    }
  }, [cidParam, sessionId])

  const { items, loadOlder, loadNewer, reportRead, hasMoreOlder } = useConversationThread(sessionId, { anchor: anchorSeq, pageSize: 60, pollMs: 4000 })

  // anchor highlight
  const [highlightSeq, setHighlightSeq] = useState<number | undefined>(anchorSeq)
  useEffect(() => { setHighlightSeq(anchorSeq) }, [anchorSeq])
  useEffect(() => {
    if (!highlightSeq) return
    const el = listRef.current?.querySelector(`[data-seq="${highlightSeq}"]`)
    if (el && 'scrollIntoView' in el) {
      (el as HTMLElement).scrollIntoView({ block: 'center' })
    }
  }, [items, highlightSeq])
  useEffect(() => { if (items.length) reportRead() }, [items, reportRead])

  const sendMutation = useSendMessage()
  const canSend = useMemo(() => input.trim().length > 0 && !sendMutation.isPending, [input, sendMutation.isPending])

  //

  // K线独立 Inspector 后续接入；不再写入消息流。

  async function handleSubmit(raw: string) {
    const text = raw.trim()
    if (!text) return
    // 轻量 optimistic：仅在 UI 显示 pending 文本，不伪造 seq/assistant 影子
    setInput('')
    setPendingTexts((prev) => [...prev, text])
    sendMutation.mutate(
      { session_id: sessionId, message: text },
      {
        onSuccess: (resp) => {
          const cid = resp?.session_id || sessionId
          if (cid && cid !== sessionId) {
            setSessionId(cid)
            persistSessionId(cid)
            nav(`/chat?cid=${encodeURIComponent(cid)}`)
          }
          setPendingTexts((prev) => prev.slice(1))
          // 拉取新项
          setTimeout(() => { loadNewer().catch(() => undefined) }, 100)
        },
        onError: (err: unknown) => {
          const e = err as { message?: string }
          message.error(e?.message || '发送失败')
          setPendingTexts((prev) => prev.slice(1))
        }
      }
    )
  }

  // Send a follow-up message triggered by recommendation card quick actions
  async function sendFollowup(text: string) {
    const t = (text || '').trim()
    if (!t) return
    setPendingTexts((prev) => [...prev, t])
    sendMutation.mutate(
      { session_id: sessionId, message: t },
      {
        onSuccess: () => {
          setPendingTexts((prev) => prev.slice(1))
          setTimeout(() => { loadNewer().catch(() => undefined) }, 80)
        },
        onError: () => {
          setPendingTexts((prev) => prev.slice(1))
          message.error('发送失败')
        }
      }
    )
  }

  const center = (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40
          setAtBottom(nearBottom)
        }}
        style={{ overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12, borderRadius: 8, minHeight: 200, maxHeight: '60vh' }}
      >
        {hasMoreOlder && (
          <div style={{ textAlign: 'center', marginBottom: 8 }}>
            <a onClick={() => { loadOlder().catch(()=>undefined) }}>加载更早消息</a>
          </div>
        )}
        {(items.length === 0 && pendingTexts.length === 0) && <Typography.Text type="secondary">示例：给我推荐3只低估值</Typography.Text>}
        <List dataSource={items} renderItem={(it: ThreadItem) => (
          <List.Item key={`${it.seq}`} data-seq={it.seq} style={{ display: 'block', border: 'none', padding: 0, background: (highlightSeq && it.seq === highlightSeq) ? 'rgba(255, 247, 173, 0.5)' : undefined }}>
            <ThreadItemRenderer item={it} onAsk={sendFollowup} />
          </List.Item>
        )} />
        {pendingTexts.map((t, i) => (
          <div key={`pending-${i}`}><MessageBubble role='user' content={t + '  (发送中...)'} /></div>
        ))}
      </div>
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="对话指令：如 给我推荐3只低估值 / 查询 600519 K线 / 查看进度"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              const native = e.nativeEvent as unknown as { isComposing?: boolean }
              if (native?.isComposing) return
              e.preventDefault()
              if (canSend) handleSubmit(input)
            }
          }}
        />
        {sendMutation.isPending && <div style={{ display: 'flex', alignItems: 'center', padding: '0 8px' }}><Spin /></div>}
      </Space.Compact>
      {!atBottom && (
        <>
          {hasNew && (
            <div
              onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }}
              style={{ cursor: 'pointer', color: '#1677ff', textAlign: 'center', margin: '6px 0' }}
            >有新内容，点击查看</div>
          )}
          <FloatButton shape="square" type="primary" tooltip="回到底部" style={{ right: 24, bottom: 24 }} onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false); setHighlightSeq(undefined) }} />
        </>
      )}
    </div>
  )

  // Decision Snapshot: follow the latest recommendation artifact in current thread
  const latestArtifactId = useMemo(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it = items[i]
      if (it.kind === 'recommendation' && it.artifact_id) return it.artifact_id
    }
    return null
  }, [items])

  const [snapshot, setSnapshot] = useState<RecommendationArtifact | null>(null)
  useEffect(() => {
    let mounted = true
    if (!latestArtifactId) { setSnapshot(null); return }
    getRecommendationArtifact(latestArtifactId).then((d) => { if (mounted) setSnapshot(asRecommendationArtifact(d)) }).catch(() => undefined)
    return () => { mounted = false }
  }, [latestArtifactId])

  const right = (
    <div style={{ height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card size="small" title="Decision Snapshot">
        {snapshot && snapshot.v2 ? (
          <div>
            <div>run_id: {snapshot.v2.run_id || '-'}</div>
            <div>as_of: {snapshot.v2.as_of || '-'}</div>
            <div>tradeable: {String(!!snapshot.v2.tradeable)}</div>
            {snapshot.v2.run_gating && <div>run_gating: {String((snapshot.v2 as any).run_gating.decision)}</div>}
            {!snapshot.v2.tradeable && snapshot.v2.reason && <div>reason: {snapshot.v2.reason}</div>}
            {Array.isArray((snapshot.v2 as any).items) && (snapshot.v2 as any).items.length > 0 && (
              <div style={{ marginTop: 4 }}>top symbols: {(snapshot.v2 as any).items.slice(0,3).map((it: any) => String(it.symbol)).join(', ')}</div>
            )}
            {Array.isArray((snapshot.v2 as any).themes) && (snapshot.v2 as any).themes.length > 0 && (
              <div style={{ marginTop: 4 }}>themes: {(snapshot.v2 as any).themes.slice(0,6).map((t: any) => String(t)).join(', ')}</div>
            )}
            <div style={{ marginTop: 8 }}>
              {snapshot.v2.run_id && (
                <Space size={8}>
                  <a onClick={() => {
                    const q = new URLSearchParams(); q.set('run_id', String(snapshot.v2!.run_id));
                    if (Array.isArray((snapshot.v2 as any).items) && (snapshot.v2 as any).items.length >= 2) {
                      const pair = (snapshot.v2 as any).items.slice(0,2).map((it:any)=>String(it.symbol))
                      q.set('symbols', pair.join(','))
                    }
                    window.location.assign(`/compare?${q.toString()}`)
                  }}>对比页</a>
                  <a onClick={() => { const q=new URLSearchParams(); q.set('run_id', String(snapshot.v2!.run_id)); window.location.assign(`/sim?${q.toString()}`) }}>研究台</a>
                </Space>
              )}
            </div>
          </div>
        ) : (
          <Typography.Text type="secondary">暂无</Typography.Text>
        )}
      </Card>
      <KlineInspector />
      <ToolsPanel
        conversationId={sessionId}
        onEnsureConversation={(cid) => { setSessionId(cid); persistSessionId(cid) }}
        onRefresh={() => { /* no-op for new model; polling handles newer items */ }}
      />
    </div>
  )

  return (
    <Card title="对话">
      <WorkbenchLayout
        left={<div className="workbench-scroll" style={{ height: '60vh' }}><Conversations /></div>}
        center={center}
        right={right}
      />
    </Card>
  )
}

function ThreadItemRenderer({ item, onAsk }: { item: ThreadItem; onAsk?: (text: string) => void }) {
  if (item.kind === 'text') {
    return <MessageBubble role={item.role === 'system' ? 'assistant' : item.role} content={item.content} />
  }
  if (item.kind === 'status') {
    return <MessageBubble role="assistant" content={item.message || ''} />
  }
  if (item.kind === 'recommendation') {
    return <RecommendationItemView artifactId={item.artifact_id} onAsk={onAsk} />
  }
  return null
}

function RecommendationItemView({ artifactId, onAsk }: { artifactId: string; onAsk?: (text: string) => void }) {
  const [data, setData] = useState<RecommendationArtifact | null>(null)
  const { openKline } = useSelectedArtifact()
  useEffect(() => {
    let mounted = true
    getRecommendationArtifact(artifactId)
      .then((d) => { if (mounted) setData(asRecommendationArtifact(d)) })
      .catch(() => undefined)
    return () => { mounted = false }
  }, [artifactId])
  if (!data) return <Typography.Text type="secondary">加载推荐卡…</Typography.Text>
  return (
    <RecommendationDetail
      artifact={data}
      onAsk={onAsk || (async (text: string) => {
        const sid = getOrCreateSessionId()
        try { await chatApi({ session_id: sid, message: text }) } catch (e) { /* ignore */ }
      })}
      onShowKline={(sym) => {
        const p = data.picks.find((x) => x.symbol === sym)
        const overlay = p?.trade_plan ? { bands: p.trade_plan.bands, chip: p.chip } : { chip: p?.chip }
        openKline(sym, overlay)
      }}
    />
  )
}
