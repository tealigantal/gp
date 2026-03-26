import { useEffect, useMemo, useRef, useState } from 'react'
import { Card, FloatButton, Input, List, Space, Spin, Typography, message } from 'antd'
import { useLocation, useNavigate } from 'react-router-dom'
import MessageBubble from '../components/MessageBubble'
import RightContextPanel from '../features/chat/RightContextPanel'
import Conversations from './Conversations'
import KlineInspector from '../features/artifacts/KlineInspector'
import { useSelectedArtifact } from '../features/artifacts/useSelectedArtifact'
import { setSessionId as persistSessionId } from '../utils/session'
import { useConversationThread } from '../features/thread/useConversationThread'
import { useSendMessage } from '../features/thread/useSendMessage'
import { setChatFocus } from '../api/client'
import { getOrCreateSessionId } from '../utils/session'
import type { ThreadItem } from '../api/contracts'

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
  const { openKline } = useSelectedArtifact()

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

  // Restore right panel from latest assistant bundle
  useEffect(() => {
    for (let i = items.length - 1; i >= 0; i--) {
      const it: any = items[i]
      if (it?.kind === 'assistant_bundle' && it?.bundle?.right_panel) {
        setRightPanel(it.bundle.right_panel as Record<string, unknown>)
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
    // optimistic UI
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
    <div style={{ height: '60vh', display: 'flex', flexDirection: 'column' }}>
      <div ref={listRef} style={{ flex: 1, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 4, padding: 8 }}
        onScroll={(e) => {
          const el = e.currentTarget
          const atBottomNow = el.scrollTop + el.clientHeight >= el.scrollHeight - 4
          if (atBottom !== atBottomNow) setAtBottom(atBottomNow)
        }}
      >
        {hasMoreOlder && (
          <div style={{ textAlign: 'center', margin: '6px 0' }}>
            <a onClick={() => loadOlder().catch(() => undefined)}>加载更早</a>
          </div>
        )}
        {items.map((it) => (
          <div key={it.seq} data-seq={it.seq} style={{ marginBottom: 8 }}>
            <ThreadItemRenderer item={it} onOpenKline={openKline} />
          </div>
        ))}
        {pendingTexts.map((t, i) => (
          <div key={`pending-${i}`} style={{ opacity: 0.6 }}>
            <MessageBubble role="user" content={t} />
          </div>
        ))}
      </div>
      <Space.Compact style={{ marginTop: 8 }}>
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="对话指令：如 推荐 / 查询 K线 / 查看进度"
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
            <div onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false) }}
              style={{ cursor: 'pointer', color: '#1677ff', textAlign: 'center', margin: '6px 0' }}
            >有新内容，点击查看</div>
          )}
          <FloatButton shape="square" type="primary" tooltip="回到底部" style={{ right: 24, bottom: 24 }} onClick={() => { listRef.current?.scrollTo({ top: 999999, behavior: 'smooth' }); setHasNew(false); setHighlightSeq(undefined) }} />
        </>
      )}
    </div>
  )

  const right = (
    <div style={{ height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12 }}>
      <RightContextPanel panel={rightPanel} sessionId={sessionId}
        onForceRefreshCompleted={() => {
          // 不自动变更右侧详情，仅拉取新消息
          setTimeout(() => { loadNewer().catch(() => undefined) }, 150)
        }}
      />
      <KlineInspector />
    </div>
  )

  return (
    <Card title="对话">
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr 320px', gap: 12 }}>
        <div className="workbench-scroll" style={{ height: '60vh' }}><Conversations /></div>
        {center}
        {right}
      </div>
    </Card>
  )
}

function ThreadItemRenderer({ item, onOpenKline }: { item: ThreadItem; onOpenKline?: (symbol: string) => void }) {
  if (item.kind === 'text') {
    return <MessageBubble role={item.role} content={item.content} />
  }
  if (item.kind === 'assistant_bundle') {
    const b: any = (item as any).bundle
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {typeof b?.text === 'string' && b.text && (
          <MessageBubble role="assistant" content={b.text} />
        )}
        {Array.isArray(b?.cards) && b.cards.map((c: any, idx: number) => {
          if (c?.type === 'recommendation') {
            const items = Array.isArray(c?.data?.items) ? c.data.items : []
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || `推荐清单 · ${items.length}`}>
                <List dataSource={items} renderItem={(it: any) => (
                  <List.Item key={String(it.symbol)} actions={[<a key="k" onClick={() => onOpenKline?.(String(it.symbol))}>查看K线</a>] }>
                    <Space>
                      <Typography.Text strong>{String(it.symbol)}</Typography.Text>
                      {it.gating_decision?.decision && <Typography.Text type="secondary">{String(it.gating_decision.decision)}</Typography.Text>}
                      <Typography.Text type="secondary">{String(it.strategy || it.strategy_label || '')}</Typography.Text>
                    </Space>
                  </List.Item>
                )} />
              </Card>
            )
          }
          if (c?.type === 'pick_detail') {
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || `标的 ${String(c.focus_symbol || '')}`}>
                研究摘要：{String((c.data || {}).thesis || '')}
              </Card>
            )
          }
          if (c?.type === 'exit_decision') {
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || `卖出判断`}>
                {String((c.data || {}).summary_reason || '')}
              </Card>
            )
          }
          if (c?.type === 'selection_explain') {
            const d = c.data || {}
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || '入选说明'}>
                <div>symbols: {(d.selection_set_symbols || []).join(', ')}</div>
                <div>rationale: {String(d.ranking_rationale || '')}</div>
              </Card>
            )
          }
          if (c?.type === 'no_trade') {
            const d = c.data || {}
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || '今日不交易'}>
                <div>reason: {String(d.reason || '')}</div>
              </Card>
            )
          }
          if (c?.type === 'compare') {
            const d = c.data || {}
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || '对比'}>
                <div>symbols: {(c.symbols || []).join(', ')}</div>
                <div>winner: {String(d.winner || '')}</div>
              </Card>
            )
          }
          if (c?.type === 'run_change') {
            const d = c.data || {}
            return (
              <Card key={`card-${idx}`} size="small" title={c.title || '本轮变更'}>
                <div>added: {(d.added_symbols || []).join(', ')}</div>
                <div>removed: {(d.removed_symbols || []).join(', ')}</div>
              </Card>
            )
          }
          return null
        })}
      </div>
    )
  }
  return null
}
