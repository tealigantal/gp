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
  getThreadItems: (...args: any[]) => getThreadItems(...args),
  chat: (...args: any[]) => chatApi(...args),
  getConversationSummaries: (...args: any[]) => getConversationSummaries(...args),
  getRecommendationArtifact: (...args: any[]) => getRecommendationArtifact(...args),
}))

vi.mock('../api/adapters', async (orig) => {
  const base = await orig()
  return { ...base as any, asRecommendationArtifact: (x: any) => x }
})

describe('Chat thread', () => {
  it('renders thread around anchor and refreshes after send', async () => {
    // polyfill matchMedia for antd responsive
    ;(window as any).matchMedia = (window as any).matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
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
})
