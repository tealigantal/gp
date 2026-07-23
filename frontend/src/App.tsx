import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { deleteConversation, friendlyError, getConversation, getConversations, getHealth, getPublication, sendChat } from './api'
import type { ConversationSession, ConversationTurn, HealthStatus, RecommendationPublication } from './contracts'
import { ArrowIcon, ChatIcon, ClockIcon, PlusIcon, RefreshIcon, ShieldIcon, SparkIcon, TrashIcon, TrendIcon } from './Icons'

const prompts = ['今天最值得关注哪几只？', '为什么现在不能直接买？', '比较前三名的风险和胜率']

const phaseLabels: Record<string, string> = {
  preopen: '开盘前', morning: '上午交易', lunch: '午间休市', afternoon: '下午交易',
  closing_auction: '收盘竞价', postclose: '已收盘', closed: '休市',
}

const reasonLabels: Record<string, string> = {
  market_not_in_trading_phase: '当前不在连续交易时段',
  daily_evidence_pending: '日线证据仍在准备',
  runtime_unavailable: '盘中执行数据暂不可用',
  runtime_pending: '盘中执行状态正在更新',
  runtime_snapshot_unavailable: '盘中行情快照暂不可用',
  runtime_symbol_missing: '当前候选缺少盘中行情',
  runtime_session_not_current: '明日计划尚未进入对应交易日',
  candidate_universe_incomplete: '全市场候选范围尚不完整',
  no_selected_candidate: '当前没有通过筛选的候选',
  no_selected_candidates: '当前没有通过筛选的候选',
}

const signalLabels: Record<string, string> = {
  trend_continuation: '趋势延续', breakout_pullback: '突破回踩', structure_watch: '结构观察',
  trend: '趋势信号',
}

const uid = () => `web_${Date.now()}_${Math.random().toString(16).slice(2)}`
const newSessionId = () => `session_web_${Date.now()}_${Math.random().toString(16).slice(2)}`
const dateTime = (value: string | null | undefined) => value ? new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) : '—'
const percent = (value: number) => `${(value * 100).toFixed(1)}%`
const price = (value: number | null | undefined) => value == null ? '—' : `¥${value.toFixed(2)}`
const shortId = (value: string) => value.replace(/^[^_]+_/, '').slice(0, 8)
const reasonText = (reason: string) => reasonLabels[reason] || '详细原因请查看当前决策说明'

async function getConsistentCoreState() {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const [health, publication] = await Promise.all([getHealth(), getPublication()])
    if (health.current_publication_id === publication.publication_id) return { health, publication }
  }
  throw new Error('当前状态正在切换')
}

export function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [publication, setPublication] = useState<RecommendationPublication | null>(null)
  const [sessions, setSessions] = useState<ConversationSession[]>([])
  const [activeSession, setActiveSession] = useState<ConversationSession | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [turns, setTurns] = useState<ConversationTurn[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [sendingSessionId, setSendingSessionId] = useState<string | null>(null)
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null)
  const [deletionNotice, setDeletionNotice] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [connectionStale, setConnectionStale] = useState(false)
  const [publicationPlanById, setPublicationPlanById] = useState<Record<string, string>>({})
  const [retryAttempt, setRetryAttempt] = useState<{ message: string; clientTurnId: string; sessionId: string } | null>(null)
  const threadEnd = useRef<HTMLDivElement>(null)
  const syncSequence = useRef(0)
  const manualSyncSequence = useRef(0)
  const sessionRequestSequence = useRef(0)
  const activeSessionIdRef = useRef<string | null>(null)
  const deletedSessionIds = useRef(new Set<string>())
  const sending = sendingSessionId !== null

  const selectActiveSessionId = useCallback((sessionId: string | null) => {
    activeSessionIdRef.current = sessionId
    setActiveSessionId(sessionId)
  }, [])

  const acceptSessions = useCallback((nextSessions: ConversationSession[]) => {
    setSessions(nextSessions.filter((session) => !deletedSessionIds.current.has(session.session_id)))
  }, [])

  const rememberPublicationPlan = useCallback((nextPublication: RecommendationPublication) => {
    setPublicationPlanById((current) => {
      if (current[nextPublication.publication_id] === nextPublication.plan_id) return current
      return { ...current, [nextPublication.publication_id]: nextPublication.plan_id }
    })
  }, [])

  const syncState = useCallback(async (quiet = false) => {
    const sequence = ++syncSequence.current
    if (!quiet) {
      manualSyncSequence.current = sequence
      setRefreshing(true)
    }
    try {
      const [nextCore, nextSessions] = await Promise.allSettled([
        getConsistentCoreState(), getConversations(),
      ])
      if (sequence !== syncSequence.current) return
      if (nextCore.status === 'fulfilled') {
        setHealth(nextCore.value.health)
        setPublication(nextCore.value.publication)
        rememberPublicationPlan(nextCore.value.publication)
      }
      if (nextSessions.status === 'fulfilled') acceptSessions(nextSessions.value)
      const coreFailed = nextCore.status === 'rejected'
      setConnectionStale(coreFailed)
      if (!quiet) {
        const failed = [nextCore, nextSessions].find((item) => item.status === 'rejected')
        setError(failed?.status === 'rejected' ? friendlyError(failed.reason) : null)
      }
    } finally {
      if (!quiet && manualSyncSequence.current === sequence) setRefreshing(false)
    }
  }, [acceptSessions, rememberPublicationPlan])

  useEffect(() => {
    syncState().finally(() => setLoading(false))
    const timer = window.setInterval(() => void syncState(true), 30_000)
    return () => window.clearInterval(timer)
  }, [syncState])

  useEffect(() => {
    if (typeof threadEnd.current?.scrollIntoView === 'function') {
      threadEnd.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [turns, sending])

  const openSession = async (sessionId: string) => {
    const requestSequence = ++sessionRequestSequence.current
    selectActiveSessionId(sessionId)
    setError(null)
    try {
      const detail = await getConversation(sessionId)
      if (requestSequence !== sessionRequestSequence.current) return
      setActiveSession(detail.session)
      setTurns([...detail.turns].sort((a, b) => a.sequence - b.sequence))
    } catch (cause) {
      if (requestSequence !== sessionRequestSequence.current) return
      setActiveSession(null)
      setTurns([])
      setError(friendlyError(cause))
    }
  }

  const newSession = () => {
    sessionRequestSequence.current += 1
    selectActiveSessionId(null)
    setActiveSession(null)
    setTurns([])
    setDraft('')
    setError(null)
    setRetryAttempt(null)
  }

  const removeSession = async (session: ConversationSession) => {
    if (deletingSessionId || sendingSessionId === session.session_id || !window.confirm(`删除 ${dateTime(session.updated_at)} 的对话（发布物 ${shortId(session.active_publication_id)}）及全部消息？此操作无法撤销。`)) return
    setDeletingSessionId(session.session_id)
    setError(null)
    try {
      await deleteConversation(session.session_id)
      deletedSessionIds.current.add(session.session_id)
      syncSequence.current += 1
      setSessions((current) => current.filter((item) => item.session_id !== session.session_id))
      if (activeSessionIdRef.current === session.session_id) newSession()
      setDeletionNotice(`已删除 ${dateTime(session.updated_at)} 的对话`)
      void syncState(true)
    } catch (cause) {
      setError(friendlyError(cause))
    } finally {
      setDeletingSessionId(null)
    }
  }

  const submit = async (message = draft) => {
    const text = message.trim()
    if (!text || sending || (deletingSessionId !== null && deletingSessionId === activeSessionId)) return
    const clientTurnId = retryAttempt?.message === text ? retryAttempt.clientTurnId : uid()
    const targetSessionId = activeSessionId || (retryAttempt?.message === text ? retryAttempt.sessionId : newSessionId())
    if (!activeSessionId) selectActiveSessionId(targetSessionId)
    const optimistic: ConversationTurn = {
      turn_id: clientTurnId, session_id: targetSessionId, publication_id: publication?.publication_id || '',
      sequence: Number.MAX_SAFE_INTEGER, role: 'user', content: text, created_at: new Date().toISOString(), client_turn_id: clientTurnId,
    }
    setTurns((current) => [...current, optimistic])
    setDraft('')
    setError(null)
    setSendingSessionId(targetSessionId)
    try {
      const response = await sendChat(text, clientTurnId, targetSessionId)
      selectActiveSessionId(response.session_id)
      rememberPublicationPlan(response.publication)
      const detail = await getConversation(response.session_id)
      setActiveSession(detail.session)
      setTurns([...detail.turns].sort((a, b) => a.sequence - b.sequence))
      acceptSessions(await getConversations())
      setRetryAttempt(null)
      void syncState(true)
    } catch (cause) {
      setTurns((current) => current.filter((turn) => turn.turn_id !== clientTurnId))
      setDraft(text)
      setRetryAttempt({ message: text, clientTurnId, sessionId: targetSessionId })
      setError(friendlyError(cause))
    } finally {
      setSendingSessionId(null)
    }
  }

  const selected = useMemo(() => publication?.candidates.filter((candidate) => candidate.disposition === 'selected') || [], [publication])
  const marketLabel = phaseLabels[health?.market_phase || ''] || '等待市场状态'
  const tradeable = !connectionStale && publication?.decision.tradeable_now === true
  const sessionPlanId = activeSession ? publicationPlanById[activeSession.active_publication_id] : null
  const sessionPublicationMismatch = Boolean(activeSession && publication && sessionPlanId && sessionPlanId !== publication.plan_id)
  const sessionPublicationUnknown = Boolean(activeSession && publication && !sessionPlanId && activeSession.active_publication_id !== publication.publication_id)
  const sessionRuntimeUpdated = Boolean(activeSession && publication && sessionPlanId === publication.plan_id && activeSession.active_publication_id !== publication.publication_id)

  if (loading) return <div className="loading-screen"><div className="loading-mark"><SparkIcon /></div><p>正在连接决策引擎</p></div>

  return (
    <div className="app-shell">
      <a className="skip-link" href="#chat-main">跳到聊天</a>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark"><TrendIcon /></div>
          <div><strong>GP</strong><span>决策智能体</span></div>
        </div>

        <button className="new-chat" onClick={newSession}><PlusIcon />新对话</button>

        <div className="history-label"><span>最近对话</span><span>{sessions.length}</span></div>
        <span className="sr-only" role="status" aria-live="polite">{deletionNotice}</span>
        <nav className="history" aria-label="最近对话">
          {sessions.length === 0 ? <p className="history-empty">你的荐股问答会保存在这里</p> : sessions.map((session) => (
            <div className="history-row" key={session.session_id}>
              <button className={session.session_id === activeSessionId ? 'history-item active' : 'history-item'} onClick={() => void openSession(session.session_id)}>
                <ChatIcon />
                <span><strong>{deletingSessionId === session.session_id ? '正在删除…' : session.session_id === activeSessionId ? '当前对话' : `荐股问答 · ${dateTime(session.updated_at)}`}</strong><small>发布物 {shortId(session.active_publication_id)}</small></span>
              </button>
              <button className="history-delete" onClick={() => void removeSession(session)} disabled={deletingSessionId !== null || sendingSessionId === session.session_id} aria-label={`删除对话 ${dateTime(session.updated_at)} 发布物 ${shortId(session.active_publication_id)}`} title="删除对话"><TrashIcon /></button>
            </div>
          ))}
        </nav>

        <div className="engine-card">
          <span className={health?.daily_data_state === 'ready' ? 'live-dot ready' : 'live-dot'} />
          <div><strong>决策引擎{health?.daily_data_state === 'ready' ? '已就绪' : '准备中'}</strong><small>日线证据 {health?.daily_evidence_date || '待更新'}</small></div>
          <ShieldIcon />
        </div>
      </aside>

      <main className="workspace" id="chat-main">
        <header className="topbar">
          <div>
            <span className="eyebrow">对话决策工作台</span>
            <h1>和你的 A 股决策 Agent 对话</h1>
            <p>基于真实市场证据生成 1–3 日计划，模型只解释，不替算法选股。</p>
          </div>
          <div className="top-actions">
            <div className={tradeable ? 'market-pill tradeable' : 'market-pill'}><span />{connectionStale ? '状态连接中断 · 禁止执行' : `${marketLabel} · ${tradeable ? '可执行' : '暂不可执行'}`}</div>
            <button className="icon-button" onClick={() => void syncState()} disabled={refreshing} aria-label="同步最新状态"><RefreshIcon className={refreshing ? 'spin' : ''} /></button>
          </div>
        </header>

        <section className="chat-panel">
          <div className="thread" aria-live="polite">
            {turns.length === 0 ? (
              <div className="welcome">
                <div className="welcome-orb"><SparkIcon /></div>
                <span className="eyebrow">GP 决策智能体</span>
                <h2>今天，想先看什么？</h2>
                <p>可以直接问候选、买入条件、风险，或比较当前计划中的标的。每个回答都绑定同一份决策发布物。</p>
                <div className="prompt-grid">
                  {prompts.map((prompt) => <button key={prompt} onClick={() => void submit(prompt)}><span>{prompt}</span><ArrowIcon /></button>)}
                </div>
              </div>
            ) : turns.map((turn) => (
              <article key={turn.turn_id} className={`message ${turn.role === 'user' ? 'user' : 'assistant'}`}>
                <div className="avatar">{turn.role === 'user' ? '你' : <SparkIcon />}</div>
                <div className="message-body"><div className="message-meta"><strong>{turn.role === 'user' ? '你' : 'GP Agent'}</strong><time>{dateTime(turn.created_at)}</time></div><p>{turn.content}</p></div>
              </article>
            ))}
            {sending ? <article className="message assistant"><div className="avatar"><SparkIcon /></div><div className="message-body"><div className="message-meta"><strong>GP Agent</strong></div><div className="typing"><span /><span /><span /></div><small className="thinking-copy">正在读取当前发布物并组织回答…</small></div></article> : null}
            {error ? <div className="error-banner" role="alert"><strong>本次请求未完成</strong><span>{error}</span></div> : null}
            <div ref={threadEnd} />
          </div>

          <div className="composer-wrap">
            <div className="composer">
              <textarea value={draft} onChange={(event) => { setDraft(event.target.value); if (event.target.value !== retryAttempt?.message) setRetryAttempt(null) }} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit() } }} placeholder="问问今天的候选、风险或执行条件…" rows={1} disabled={sending || (deletingSessionId !== null && deletingSessionId === activeSessionId)} aria-label="聊天输入" />
              <button onClick={() => void submit()} disabled={!draft.trim() || sending || (deletingSessionId !== null && deletingSessionId === activeSessionId)} aria-label="发送消息"><ArrowIcon /></button>
            </div>
            <div className="composer-note"><span><ShieldIcon />{activeSession ? '回答沿用本会话绑定发布物' : '回答只引用当前决策发布物'}</span><span>Enter 发送 · Shift + Enter 换行</span></div>
          </div>
        </section>
      </main>

      <aside className="insight-panel">
        <div className="insight-head"><div><span className="eyebrow">当前决策简报</span><h2>今日决策</h2></div><span className={`decision-badge ${tradeable ? 'positive' : ''}`}>{publication?.decision.plan_status === 'recommend' ? '已有计划' : '暂无推荐'}</span></div>

        <div className="asof-card"><ClockIcon /><div><span>计划交易日</span><strong>{health?.market_session_date || '待发布'}</strong><small>证据截至 {health?.daily_evidence_date || '—'}</small></div></div>

        {connectionStale ? <div className="state-warning" role="alert"><ShieldIcon /><div><strong>实时状态已断开</strong><span>旧数据仅供回看，当前执行状态按不可用处理。连接恢复后会自动更新。</span></div></div> : null}

        {sessionRuntimeUpdated ? <div className="state-warning"><ClockIcon /><div><strong>同一计划的执行状态已更新</strong><span>对话绑定的候选计划未变，右侧展示的是最新盘中执行状态。</span></div></div> : null}

        {sessionPublicationMismatch ? (
          <div className="empty-publication historical-notice"><ClockIcon /><h3>正在查看历史对话</h3><p>此会话绑定发布物 {shortId(activeSession!.active_publication_id)}，与当前决策不同。为避免事实错配，历史会话中不并排展示当前候选；新建对话可回到当前决策。</p></div>
        ) : sessionPublicationUnknown ? (
          <div className="empty-publication historical-notice"><ClockIcon /><h3>正在查看已绑定对话</h3><p>此会话绑定较早的发布物 {shortId(activeSession!.active_publication_id)}，当前公开接口无法确认它是否属于同一计划。为避免混用事实，暂不并排展示当前候选；继续提问后会依据会话绑定谱系自动判定。</p></div>
        ) : publication ? (
          <>
            <section className="summary-strip">
              <div><span>入选</span><strong>{selected.length}</strong><small>进入评分 {publication.candidates.length}</small></div>
              <div><span>执行状态</span><strong className={tradeable ? 'green' : 'amber'}>{tradeable ? '可执行' : '等待'}</strong><small>{marketLabel}</small></div>
            </section>

            <div className="section-title"><span>算法入选</span><small>按引擎原始排名</small></div>
            <div className="candidate-list">
              {selected.length ? selected.map((candidate) => (
                <article className="candidate" key={candidate.symbol}>
                  <div className="candidate-top"><span className="rank">{candidate.ranking.rank}</span><div><strong>{candidate.name || candidate.symbol}</strong><small>{candidate.symbol} · {signalLabels[candidate.signal.label] || '算法信号'}</small></div><span className="score">{candidate.adaptive_score.toFixed(3)}</span></div>
                  <div className="metrics"><span>3日概率 <strong>{percent(candidate.probability.probability)}</strong></span><span>执行风险 <strong>{percent(candidate.risk.execution_risk)}</strong></span></div>
                  <div className="trade-plan"><div><span>观察区间</span><strong>{price(candidate.trade_plan.entry_low)} – {price(candidate.trade_plan.entry_high)}</strong></div><div><span>止损参考</span><strong>{price(candidate.trade_plan.stop_price)}</strong></div></div>
                </article>
              )) : <div className="empty-candidates"><ShieldIcon /><strong>当前没有入选标的</strong><span>系统选择失败关闭，不会用旧候选填充。</span></div>}
            </div>

            {publication.decision.reason_codes.length ? <div className="reason-box"><strong>当前限制</strong>{publication.decision.reason_codes.map((reason) => <span key={reason}>{reasonText(reason)}</span>)}</div> : null}

            <div className="lineage"><span>发布物 {shortId(publication.publication_id)}</span><span>引擎 {publication.lineage.producer_revision}</span><span>{dateTime(publication.published_at)} 发布</span></div>
          </>
        ) : <div className="empty-publication"><ShieldIcon /><h3>等待第一份有效计划</h3><p>候选数据准备完整后，这里会展示可追溯的推荐发布物。</p></div>}
      </aside>
    </div>
  )
}
