import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, FloatButton, Input, List, Space, Spin, Typography, message } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import MessageBubble from '../components/MessageBubble'
import RecommendationDetail from '../features/recommendation/RecommendationDetail'
import WorkbenchLayout from '../components/WorkbenchLayout'
import ToolsPanel from '../components/ToolsPanel'
import RightContextPanel from '../features/chat/RightContextPanel'
import Conversations from './Conversations'
import KlineInspector from '../features/artifacts/KlineInspector'
import { setSessionId as persistSessionId } from '../utils/session'
import { useConversationThread } from '../features/thread/useConversationThread'
import { useSendMessage } from '../features/thread/useSendMessage'
import { chat as chatApi, getRecommendationArtifact, setChatFocus } from '../api/client'
import { asRecommendationArtifact } from '../api/adapters'
import { useSelectedArtifact } from '../features/artifacts/useSelectedArtifact'
import { getOrCreateSessionId } from '../utils/session'
import type { ThreadItem, RecommendationArtifact } from '../api/contracts'
import NoTradeCard from '../features/chat/cards/NoTradeCard'
import PickDetailCard from '../features/chat/cards/PickDetailCard'
import CompareCard from '../features/chat/cards/CompareCard'
import ExitDecisionCard from '../features/chat/cards/ExitDecisionCard'
import RunChangeCard from '../features/chat/cards/RunChangeCard'

export default function Chat() {
  const nav = useNavigate()
  const loc = useLocation()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [pendingTexts, setPendingTexts] = useState<string[]>([])
  const [rightPanel, setRightPanel] = useState<Record<string, unknown> | null>(null)
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

  // Restore right panel from latest assistant status/card payload
  useEffect(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it: any = items[i]
      const p = it?.payload
      if (p && typeof p === 'object' && p.right_panel) {
        setRightPanel(p.right_panel as Record<string, unknown>)
        break
      }
    }
  }, [items])

  async function focusSymbol(sym: string) {
    const s = (sym || '').trim()
    if (!s) return
    const sid = sessionId || getOrCreateSessionId()
    try {
      await setChatFocus({ session_id: sid, focus_symbol: s })
      setRightPanel((prev) => ({ ...(prev || {}), focus_symbol: s }))
    } catch { /* ignore */ }
  }

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
          try { setRightPanel((resp as any)?.right_panel || null) } catch {}
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
        onSuccess: (resp) => {
          setPendingTexts((prev) => prev.slice(1))
          try { setRightPanel((resp as any)?.right_panel || null) } catch {}
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
            <ThreadItemRenderer item={it} onAsk={sendFollowup} onFocus={(s) => focusSymbol(s)} />
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
      <RightContextPanel panel={rightPanel} />
      <KlineInspector />
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

function ThreadItemRenderer({ item, onAsk, onFocus }: { item: ThreadItem; onAsk?: (text: string) => void; onFocus?: (symbol: string) => void }) {
  if (item.kind === 'text') {
    return <MessageBubble role={item.role === 'system' ? 'assistant' : item.role} content={item.content} />
  }
  if (item.kind === 'status') {
    return <MessageBubble role="assistant" content={item.message || ''} />
  }
  if (item.kind === 'recommendation') {
    return <RecommendationItemView artifactId={item.artifact_id} onAsk={onAsk} onFocus={(s) => onFocus?.(s)} />
  }
  if (item.kind === 'no_trade') {
    // Minimal: rely on preview; server may include decision later
    return <NoTradeCard decision={(item as any).decision} />
  }
  if (item.kind === 'pick_detail') {
    return <PickDetailCard symbol={(item as any).symbol} item={(item as any).payload?.item} onFocus={(s) => onFocus?.(s)} />
  }
  if (item.kind === 'compare') {
    return <CompareCard symbols={(item as any).symbols} winner_symbol={(item as any).winner_symbol} onFocus={(s) => onFocus?.(s)} />
  }
  if (item.kind === 'exit_decision') {
    const p: any = (item as any).payload || {}
    return <ExitDecisionCard symbol={(item as any).symbol} decision={(item as any).decision} summary_reason={p.summary_reason} primary_reasons={p.primary_reasons} trigger_conditions={p.trigger_conditions} risk_notes={p.risk_notes} onFocus={(s) => onFocus?.(s)} />
  }
  if (item.kind === 'run_change') {
    return <RunChangeCard summary_reason={(item as any).summary_reason} payload={(item as any).payload} onFocus={(s) => onFocus?.(s)} />
  }
  return null
}

function RecommendationItemView({ artifactId, onAsk, onFocus }: { artifactId: string; onAsk?: (text: string) => void; onFocus?: (symbol: string) => void }) {
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
      onFocus={onFocus}
      onShowKline={(sym) => {
        const p = data.picks.find((x) => x.symbol === sym)
        const overlay = p?.trade_plan ? { bands: p.trade_plan.bands, chip: p.chip } : { chip: p?.chip }
        openKline(sym, overlay)
      }}
    />
  )
}
