import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SelectedArtifactProvider } from '../features/artifacts/useSelectedArtifact'
import Chat from './Chat'

const getThreadItems = vi.fn()
const chatApi = vi.fn()
const getConversationSummaries = vi.fn()
const getRecommendationArtifact = vi.fn()

vi.mock('../api/client', () => ({
  getThreadItems: (...args: unknown[]) => getThreadItems(...(args as [])),
  chat: (...args: unknown[]) => chatApi(...(args as [])),
  getConversationSummaries: (...args: unknown[]) => getConversationSummaries(...(args as [])),
  getRecommendationArtifact: (...args: unknown[]) => getRecommendationArtifact(...(args as [])),
}))

vi.mock('../api/adapters', async (orig) => {
  const base = await orig()
  return { ...(base as Record<string, unknown>), asRecommendationArtifact: (x: unknown) => x }
})

describe('Chat thread', () => {
  it('renders thread around anchor and refreshes after send', async () => {
    // polyfill matchMedia for antd responsive
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    getConversationSummaries.mockResolvedValueOnce([])
    getThreadItems
      .mockResolvedValueOnce([
        { id: 'm9', conversation_id: 'c1', seq: 41, created_at: 't', role: 'user', kind: 'text', content: 'hi' },
        { id: 'm10', conversation_id: 'c1', seq: 42, created_at: 't', role: 'assistant', kind: 'text', content: 'hello' },
      ])
      .mockResolvedValueOnce([]) // forward initial
      .mockResolvedValueOnce([ { id: 'm11', conversation_id: 'c1', seq: 43, created_at: 't', role: 'assistant', kind: 'text', content: 'ok' } ]) // forward after send

    chatApi.mockResolvedValue({ session_id: 'c1', reply: 'ok', tool_trace: {} })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <SelectedArtifactProvider>
          <MemoryRouter initialEntries={[ '/chat?cid=c1&seq=42' ]}>
            <Chat />
          </MemoryRouter>
        </SelectedArtifactProvider>
      </QueryClientProvider>
    )

    await waitFor(() => expect(screen.getByText('hello')).toBeInTheDocument())
    const ta = screen.getByPlaceholderText('对话指令：如 给我推荐3只低估值 / 查询 600519 K线 / 查看进度') as HTMLTextAreaElement
    fireEvent.change(ta, { target: { value: 'ping' } })
    fireEvent.keyDown(ta, { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(getThreadItems).toHaveBeenCalledTimes(3))
    await waitFor(() => expect(screen.getByText('ok')).toBeInTheDocument())
  })

  it('sends follow-up from recommendation card quick actions', async () => {
    // polyfill
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))

    getConversationSummaries.mockResolvedValueOnce([])
    // anchor/backwards load
    getThreadItems
      .mockResolvedValueOnce([
        { id: 'a1', conversation_id: 'c2', seq: 1, created_at: 't', role: 'assistant', kind: 'recommendation', artifact_id: 'art-1', summary: { total: 3, top_symbols: ['AAA','BBB','CCC'] } },
      ])
      .mockResolvedValueOnce([]) // forward initial
      .mockResolvedValueOnce([ { id: 'a2', conversation_id: 'c2', seq: 2, created_at: 't', role: 'assistant', kind: 'text', content: 'ok-followup' } ]) // forward after click

    getRecommendationArtifact.mockResolvedValueOnce({
      id: 'art-1',
      v2: { artifact_version: 'v2', run_id: 'rid', as_of: '2099-01-01', tradeable: true, items: [{ symbol: 'AAA' }, { symbol: 'BBB' }], themes: [], run_gating: { decision: 'allow' } },
    })

    chatApi.mockResolvedValue({ session_id: 'c2', reply: 'ok-followup', tool_trace: {} })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <SelectedArtifactProvider>
          <MemoryRouter initialEntries={[ '/chat?cid=c2' ]}>
            <Chat />
          </MemoryRouter>
        </SelectedArtifactProvider>
      </QueryClientProvider>
    )

    // render card
    await waitFor(() => expect(getRecommendationArtifact).toHaveBeenCalled())
    // click quick action: 第二只为什么不是第一只
    const link = await screen.findByText('第二只为什么不是第一只')
    fireEvent.click(link)
    await waitFor(() => expect(getThreadItems).toHaveBeenCalledTimes(3))
    await waitFor(() => expect(screen.getByText('ok-followup')).toBeInTheDocument())
  })

  it('ranking quick action sends ranking explain text', async () => {
    const w = window as any
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    getConversationSummaries.mockResolvedValueOnce([])
    getThreadItems
      .mockResolvedValueOnce([
        { id: 'a1', conversation_id: 'c3', seq: 1, created_at: 't', role: 'assistant', kind: 'recommendation', artifact_id: 'art-2', summary: { total: 3, top_symbols: ['AAA','BBB','CCC'] } },
      ])
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([ { id: 'a2', conversation_id: 'c3', seq: 2, created_at: 't', role: 'assistant', kind: 'text', content: 'ok-ranking' } ])
    getRecommendationArtifact.mockResolvedValueOnce({ id: 'art-2', v2: { artifact_version: 'v2', run_id: 'rid2', as_of: '2099-01-01', tradeable: true, items: [{ symbol: 'AAA' }, { symbol: 'BBB' }], themes: [], run_gating: { decision: 'allow' } } })
    chatApi.mockResolvedValue({ session_id: 'c3', reply: 'ok-ranking', tool_trace: {} })
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <SelectedArtifactProvider>
          <MemoryRouter initialEntries={[ '/chat?cid=c3' ]}>
            <Chat />
          </MemoryRouter>
        </SelectedArtifactProvider>
      </QueryClientProvider>
    )
    const link = await screen.findByText('为什么是第一只')
    fireEvent.click(link)
    await waitFor(() => expect(chatApi).toHaveBeenCalled())
    const args = chatApi.mock.calls[0][0]
    expect(args.message).toMatch(/为什么第一只排第一/)
  })
})
