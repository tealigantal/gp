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
import { getRecommendationArtifact } from '../api/client'
import { asRecommendationArtifact } from '../api/adapters'
import { useSelectedArtifact } from '../features/artifacts/useSelectedArtifact'
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

  const center = (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40
          setAtBottom(nearBottom)
        }}
        style={{ flex: 1, overflowY: 'auto', padding: 8, border: '1px solid #eee', marginBottom: 12, borderRadius: 8, minHeight: 0 }}
      >
        {hasMoreOlder && (
          <div style={{ textAlign: 'center', marginBottom: 8 }}>
            <a onClick={() => { loadOlder().catch(()=>undefined) }}>加载更早消息</a>
          </div>
        )}
        {(items.length === 0 && pendingTexts.length === 0) && <Typography.Text type="secondary">示例：给我推荐3只低估值</Typography.Text>}
        <List dataSource={items} renderItem={(it: ThreadItem) => (
          <List.Item key={`${it.seq}`} data-seq={it.seq} style={{ display: 'block', border: 'none', padding: 0, background: (highlightSeq && it.seq === highlightSeq) ? 'rgba(255, 247, 173, 0.5)' : undefined }}>
            <ThreadItemRenderer item={it} />
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

  const right = (
    <div style={{ height: '100%', overflow: 'auto' }}>
      <KlineInspector />
      <ToolsPanel
        conversationId={sessionId}
        onEnsureConversation={(cid) => { setSessionId(cid); persistSessionId(cid) }}
        onRefresh={() => { /* no-op for new model; polling handles newer items */ }}
      />
    </div>
  )

  return (
    <Card title="对话" style={{ height: '100%' }} styles={{ body: { height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'hidden' } }}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, minHeight: 0 }}>
          <WorkbenchLayout left={<Conversations />} center={center} right={right} />
        </div>
      </div>
    </Card>
  )
}

function ThreadItemRenderer({ item }: { item: ThreadItem }) {
  if (item.kind === 'text') {
    return <MessageBubble role={item.role === 'system' ? 'assistant' : item.role} content={item.content} />
  }
  if (item.kind === 'status') {
    return <MessageBubble role="assistant" content={item.message || ''} />
  }
  if (item.kind === 'recommendation') {
    return <RecommendationItemView artifactId={item.artifact_id} />
  }
  return null
}

function RecommendationItemView({ artifactId }: { artifactId: string }) {
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
      onShowKline={(sym) => {
        const p = data.picks.find((x) => x.symbol === sym)
        const overlay = p?.trade_plan ? { bands: p.trade_plan.bands, chip: p.chip } : { chip: p?.chip }
        openKline(sym, overlay)
      }}
    />
  )
}
