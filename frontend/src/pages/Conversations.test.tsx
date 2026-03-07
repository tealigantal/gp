import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import Conversations from './Conversations'

vi.mock('../api/client', () => ({
  getConversationSummaries: vi.fn(async () => ([{
    id: 'c1', title: 'test conv', last_seq: 10, last_item_preview: 'hello', last_item_kind: 'text', last_item_ts: new Date().toISOString(), unread_count: 1, updated_at: new Date().toISOString()
  }])),
  deleteConversation: vi.fn(async () => ({ status: 'ok' })),
  cleanupConversations: vi.fn(async () => ({ status: 'ok', mode: 'all' })),
}))

describe('Conversations page', () => {
  it('loads and shows preview', async () => {
    // polyfill matchMedia for antd responsive
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    const qc = new QueryClient()
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Conversations />
        </MemoryRouter>
      </QueryClientProvider>
    )
    await waitFor(() => expect(screen.getByText('test conv')).toBeInTheDocument())
    expect(screen.getByText('hello')).toBeInTheDocument()
  })
})
