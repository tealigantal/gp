import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from './App'

const publication = {
  publication_id: 'publication_demo1234', plan_id: 'plan_demo', runtime_id: 'runtime_demo', published_at: '2026-07-23T18:48:51+08:00',
  decision: { plan_status: 'recommend', execution_status: 'unavailable', tradeable_now: false, reason_codes: ['market_not_in_trading_phase'] },
  lineage: { plan_id: 'plan_demo', runtime_id: 'runtime_demo', producer_revision: 'adaptive-v3', source_digest: 'digest' },
  candidates: [{
    symbol: '600030', name: '中信证券', disposition: 'selected', adaptive_score: 0.61, recommendation_strength: 'normal',
    signal: { score: 0.8, label: 'breakout_pullback', reason_codes: [] },
    probability: { probability: 0.58, confidence: 0.9, effective_sample_size: 80, uncertainty: 0.05 },
    risk: { score: 0.66, execution_risk: 0.34, reason_codes: [] }, ranking: { score: 0.1, rank: 1, reason_codes: [] },
    trade_plan: { entry_low: 26.2, entry_high: 28.9, stop_price: 25.6, take_profit_prices: [30], action: 'watch', reason_codes: [] }, reason_codes: [],
  }],
}

const health = {
  current_publication_id: publication.publication_id, plan_id: publication.plan_id, runtime_id: publication.runtime_id,
  market_session_date: '2026-07-24', daily_evidence_date: '2026-07-23', slot_closed_at: '2026-07-23T15:00:00+08:00',
  market_phase: 'postclose', daily_data_state: 'ready', runtime_data_state: 'unavailable', publication_state: 'recommend', tradeability_state: 'unavailable',
}

function jsonResponse(value: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(value) } as Response)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('GP chat workspace', () => {
  it('renders canonical publication facts without deriving a new ranking', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      return jsonResponse([])
    }))

    render(<App />)
    expect(await screen.findByText('今天，想先看什么？')).toBeInTheDocument()
    expect(screen.getByText('中信证券')).toBeInTheDocument()
    expect(screen.getByText('58.0%')).toBeInTheDocument()
    expect(screen.getByText('进入评分 1')).toBeInTheDocument()
    expect(screen.getByText('执行风险')).toBeInTheDocument()
    expect(screen.getByText('34.0%')).toBeInTheDocument()
    expect(screen.getByText('已收盘 · 暂不可执行')).toBeInTheDocument()
  })

  it('sends a new chat and replaces the optimistic turn with canonical turns', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([])
      if (url === '/api/chat' && init?.method === 'POST') return jsonResponse({ session_id: 'session_1', client_turn_id: 'client_1', publication_id: publication.publication_id, reply: '基于当前发布物回答。', publication })
      if (url === '/api/conversations/session_1') return jsonResponse({ session: { session_id: 'session_1', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }, turns: [
        { turn_id: 'u1', session_id: 'session_1', publication_id: publication.publication_id, sequence: 1, role: 'user', content: '今天推荐什么？', created_at: '2026-07-23T10:00:00Z', client_turn_id: 'client_1' },
        { turn_id: 'a1', session_id: 'session_1', publication_id: publication.publication_id, sequence: 2, role: 'assistant', content: '基于当前发布物回答。', created_at: '2026-07-23T10:01:00Z', client_turn_id: null },
      ] })
      return jsonResponse([])
    }))

    render(<App />)
    const input = await screen.findByLabelText('聊天输入')
    fireEvent.change(input, { target: { value: '今天推荐什么？' } })
    fireEvent.click(screen.getByLabelText('发送消息'))
    expect(await screen.findByText('基于当前发布物回答。')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('今天推荐什么？')).toBeInTheDocument())
  })

  it('hides the current brief while viewing a conversation bound to an older publication', async () => {
    const oldSession = { session_id: 'session_old', active_publication_id: 'publication_old', created_at: '2026-07-22T10:00:00Z', updated_at: '2026-07-22T10:01:00Z' }
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([oldSession])
      if (url === '/api/conversations/session_old') return jsonResponse({ session: oldSession, turns: [] })
      return jsonResponse([])
    }))

    render(<App />)
    expect(await screen.findByText('中信证券')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /荐股问答/ }))
    expect(await screen.findByText('正在查看已绑定对话')).toBeInTheDocument()
    expect(screen.queryByText('中信证券')).not.toBeInTheDocument()
  })

  it('keeps the current brief when a conversation publication belongs to the same plan', async () => {
    const sessionPublication = { ...publication, publication_id: 'publication_same_plan_older', runtime_id: 'runtime_older', candidates: [{ ...publication.candidates[0], name: '旧发布物候选' }] }
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([])
      if (url === '/api/chat' && init?.method === 'POST') return jsonResponse({ session_id: 'session_same_plan', client_turn_id: 'client_same_plan', publication_id: sessionPublication.publication_id, reply: '同一计划回答。', publication: sessionPublication })
      if (url === '/api/conversations/session_same_plan') return jsonResponse({ session: { session_id: 'session_same_plan', active_publication_id: sessionPublication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }, turns: [
        { turn_id: 'u-same', session_id: 'session_same_plan', publication_id: sessionPublication.publication_id, sequence: 1, role: 'user', content: '继续当前计划', created_at: '2026-07-23T10:00:00Z', client_turn_id: 'client_same_plan' },
        { turn_id: 'a-same', session_id: 'session_same_plan', publication_id: sessionPublication.publication_id, sequence: 2, role: 'assistant', content: '同一计划回答。', created_at: '2026-07-23T10:01:00Z', client_turn_id: null },
      ] })
      return jsonResponse([])
    }))

    render(<App />)
    const input = await screen.findByLabelText('聊天输入')
    fireEvent.change(input, { target: { value: '继续当前计划' } })
    fireEvent.click(screen.getByLabelText('发送消息'))
    expect(await screen.findByText('同一计划回答。')).toBeInTheDocument()
    expect(screen.queryByText('正在查看历史对话')).not.toBeInTheDocument()
    expect(screen.getByText('同一计划的执行状态已更新')).toBeInTheDocument()
    expect(screen.getByText('中信证券')).toBeInTheDocument()
    expect(screen.queryByText('旧发布物候选')).not.toBeInTheDocument()
    expect(screen.getByText('回答沿用本会话绑定发布物')).toBeInTheDocument()
  })

  it('does not let a slower conversation request overwrite the latest selection', async () => {
    const sessionA = { session_id: 'session_a', active_publication_id: publication.publication_id, created_at: '2026-07-23T09:00:00Z', updated_at: '2026-07-23T09:01:00Z' }
    const sessionB = { session_id: 'session_b', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }
    let resolveSessionA: ((response: Response) => void) | undefined
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([sessionB, sessionA])
      if (url === '/api/conversations/session_a') return new Promise<Response>((resolve) => { resolveSessionA = resolve })
      if (url === '/api/conversations/session_b') return jsonResponse({ session: sessionB, turns: [
        { turn_id: 'b1', session_id: 'session_b', publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: 'B 会话内容', created_at: '2026-07-23T10:01:00Z', client_turn_id: null },
      ] })
      return jsonResponse([])
    }))

    render(<App />)
    await screen.findByText('中信证券')
    const historyButtons = screen.getAllByRole('button', { name: /荐股问答/ })
    fireEvent.click(historyButtons[1])
    fireEvent.click(historyButtons[0])
    expect(await screen.findByText('B 会话内容')).toBeInTheDocument()
    resolveSessionA?.(await jsonResponse({ session: sessionA, turns: [
      { turn_id: 'a1', session_id: 'session_a', publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: 'A 会话内容', created_at: '2026-07-23T09:01:00Z', client_turn_id: null },
    ] }))
    await waitFor(() => expect(screen.queryByText('A 会话内容')).not.toBeInTheDocument())
    expect(screen.getByText('B 会话内容')).toBeInTheDocument()
  })

  it('deletes the active conversation after confirmation and resets the workspace', async () => {
    const session = { session_id: 'session_delete', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }
    let deleted = false
    const fetchMock = vi.fn((input: string | URL, init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse(deleted ? [] : [session])
      if (url === '/api/conversations/session_delete' && init?.method === 'DELETE') {
        deleted = true
        return jsonResponse(null, 204)
      }
      if (url === '/api/conversations/session_delete') return jsonResponse({ session, turns: [
        { turn_id: 'delete-turn', session_id: session.session_id, publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: '将被删除的对话', created_at: '2026-07-23T10:01:00Z', client_turn_id: null },
      ] })
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: /荐股问答/ }))
    expect(await screen.findByText('将被删除的对话')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /删除对话/ }))

    expect(await screen.findByText('你的荐股问答会保存在这里')).toBeInTheDocument()
    expect(screen.queryByText('将被删除的对话')).not.toBeInTheDocument()
    expect(screen.getByText('今天，想先看什么？')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/conversations/session_delete' && (init as { method?: string } | undefined)?.method === 'DELETE')).toBe(true)
  })

  it('keeps a conversation when deletion confirmation is cancelled', async () => {
    const session = { session_id: 'session_keep', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }
    const fetchMock = vi.fn((input: string | URL, _init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([session])
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(<App />)
    const deleteButton = await screen.findByRole('button', { name: /删除对话/ })
    fireEvent.click(deleteButton)

    expect(screen.getByRole('button', { name: /删除对话/ })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([, init]) => (init as { method?: string } | undefined)?.method === 'DELETE')).toBe(false)
  })

  it('keeps a newly selected conversation when an earlier deletion finishes', async () => {
    const sessionA = { session_id: 'session_delete_a', active_publication_id: publication.publication_id, created_at: '2026-07-23T09:00:00Z', updated_at: '2026-07-23T09:01:00Z' }
    const sessionB = { session_id: 'session_keep_b', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }
    let resolveDelete: ((response: Response) => void) | undefined
    let deleted = false
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse(deleted ? [sessionB] : [sessionA, sessionB])
      if (url === '/api/conversations/session_delete_a' && init?.method === 'DELETE') return new Promise<Response>((resolve) => { resolveDelete = (response) => { deleted = true; resolve(response) } })
      if (url === '/api/conversations/session_delete_a') return jsonResponse({ session: sessionA, turns: [{ turn_id: 'a-delete', session_id: sessionA.session_id, publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: 'A 内容', created_at: sessionA.updated_at, client_turn_id: null }] })
      if (url === '/api/conversations/session_keep_b') return jsonResponse({ session: sessionB, turns: [{ turn_id: 'b-keep', session_id: sessionB.session_id, publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: 'B 内容', created_at: sessionB.updated_at, client_turn_id: null }] })
      return jsonResponse([])
    }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<App />)
    const historyButtons = await screen.findAllByRole('button', { name: /荐股问答/ })
    fireEvent.click(historyButtons[0])
    await screen.findByText('A 内容')
    fireEvent.click(screen.getAllByRole('button', { name: /删除对话/ })[0])
    fireEvent.click(historyButtons[1])
    expect(await screen.findByText('B 内容')).toBeInTheDocument()
    resolveDelete?.(await jsonResponse(null, 204))

    await waitFor(() => expect(screen.queryByText('A 内容')).not.toBeInTheDocument())
    expect(screen.getByText('B 内容')).toBeInTheDocument()
  })

  it('clears a conversation selected while its deletion is pending', async () => {
    const sessionA = { session_id: 'session_pending_delete', active_publication_id: publication.publication_id, created_at: '2026-07-23T09:00:00Z', updated_at: '2026-07-23T09:01:00Z' }
    const sessionB = { session_id: 'session_initial', active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }
    let resolveDelete: ((response: Response) => void) | undefined
    let deleted = false
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: { method?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse(deleted ? [sessionB] : [sessionA, sessionB])
      if (url === '/api/conversations/session_pending_delete' && init?.method === 'DELETE') return new Promise<Response>((resolve) => { resolveDelete = (response) => { deleted = true; resolve(response) } })
      if (url === '/api/conversations/session_pending_delete') return jsonResponse({ session: sessionA, turns: [{ turn_id: 'pending-delete', session_id: sessionA.session_id, publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: '待删除内容', created_at: sessionA.updated_at, client_turn_id: null }] })
      if (url === '/api/conversations/session_initial') return jsonResponse({ session: sessionB, turns: [{ turn_id: 'initial', session_id: sessionB.session_id, publication_id: publication.publication_id, sequence: 1, role: 'assistant', content: '初始内容', created_at: sessionB.updated_at, client_turn_id: null }] })
      return jsonResponse([])
    }))
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<App />)
    const historyButtons = await screen.findAllByRole('button', { name: /荐股问答/ })
    const sessionAButton = historyButtons[0]
    fireEvent.click(historyButtons[1])
    await screen.findByText('初始内容')
    fireEvent.click(screen.getAllByRole('button', { name: /删除对话/ })[0])
    fireEvent.click(sessionAButton)
    expect(await screen.findByText('待删除内容')).toBeInTheDocument()
    resolveDelete?.(await jsonResponse(null, 204))

    expect(await screen.findByText('今天，想先看什么？')).toBeInTheDocument()
    expect(screen.queryByText('待删除内容')).not.toBeInTheDocument()
  })

  it('retries once when health and publication versions cross during polling', async () => {
    let healthReads = 0
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) {
        healthReads += 1
        return jsonResponse(healthReads === 1 ? { ...health, current_publication_id: 'publication_crossed' } : health)
      }
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      return jsonResponse([])
    }))

    render(<App />)
    expect(await screen.findByText('中信证券')).toBeInTheDocument()
    expect(healthReads).toBe(2)
    expect(screen.queryByText('实时状态已断开')).not.toBeInTheDocument()
  })

  it('renders the next-session runtime reason in Chinese', async () => {
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse({ ...publication, decision: { ...publication.decision, reason_codes: ['runtime_session_not_current'] } })
      return jsonResponse([])
    }))

    render(<App />)
    expect(await screen.findByText('明日计划尚未进入对应交易日')).toBeInTheDocument()
    expect(screen.queryByText('runtime session not current')).not.toBeInTheDocument()
  })

  it('fails closed when a later state synchronization loses the API', async () => {
    let failCore = false
    vi.stubGlobal('fetch', vi.fn((input: string | URL) => {
      const url = String(input)
      if (failCore && (url.includes('/api/health') || url.includes('/api/recommendation/current'))) return jsonResponse({ detail: 'offline' }, 503)
      if (url.includes('/api/health')) return jsonResponse({ ...health, market_phase: 'morning', tradeability_state: 'tradeable' })
      if (url.includes('/api/recommendation/current')) return jsonResponse({ ...publication, decision: { ...publication.decision, tradeable_now: true } })
      return jsonResponse([])
    }))

    render(<App />)
    expect(await screen.findByText('上午交易 · 可执行')).toBeInTheDocument()
    failCore = true
    fireEvent.click(screen.getByLabelText('同步最新状态'))
    expect(await screen.findByText('实时状态已断开')).toBeInTheDocument()
    expect(screen.getByText('状态连接中断 · 禁止执行')).toBeInTheDocument()
  })

  it('reuses the same client turn id after an uncertain failed response', async () => {
    const submittedIds: string[] = []
    const submittedSessionIds: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: string | URL, init?: { method?: string; body?: string }) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      if (url === '/api/conversations?limit=30') return jsonResponse([])
      if (url === '/api/chat') {
        const body = JSON.parse(init?.body || '{}') as { client_turn_id: string; session_id: string }
        submittedIds.push(body.client_turn_id)
        submittedSessionIds.push(body.session_id)
        if (submittedIds.length === 1) return jsonResponse({ detail: 'narration_unavailable:timeout' }, 503)
        return jsonResponse({ session_id: body.session_id, client_turn_id: body.client_turn_id, publication_id: publication.publication_id, reply: '重试成功。', publication })
      }
      if (url.startsWith('/api/conversations/session_web_')) {
        const sessionId = decodeURIComponent(url.split('/').at(-1) || '')
        return jsonResponse({ session: { session_id: sessionId, active_publication_id: publication.publication_id, created_at: '2026-07-23T10:00:00Z', updated_at: '2026-07-23T10:01:00Z' }, turns: [] })
      }
      return jsonResponse([])
    }))

    render(<App />)
    const input = await screen.findByLabelText('聊天输入')
    fireEvent.change(input, { target: { value: '保持同一次重试' } })
    fireEvent.click(screen.getByLabelText('发送消息'))
    expect(await screen.findByText('本次请求未完成')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('发送消息'))
    await waitFor(() => expect(submittedIds).toHaveLength(2))
    expect(submittedIds[1]).toBe(submittedIds[0])
    expect(submittedSessionIds[0]).toMatch(/^session_web_/)
    expect(submittedSessionIds[1]).toBe(submittedSessionIds[0])
  })

  it('does not submit Enter while a Chinese IME composition is active', async () => {
    const fetchMock = vi.fn((input: string | URL) => {
      const url = String(input)
      if (url.includes('/api/health')) return jsonResponse(health)
      if (url.includes('/api/recommendation/current')) return jsonResponse(publication)
      return jsonResponse([])
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    const input = await screen.findByLabelText('聊天输入')
    fireEvent.change(input, { target: { value: '拼音输入' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', isComposing: true })
    await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url) === '/api/chat')).toHaveLength(0))
    expect(input).toHaveValue('拼音输入')
  })
})
