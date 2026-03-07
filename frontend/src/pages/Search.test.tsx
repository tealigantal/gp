import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Search from './Search'

vi.mock('../api/client', () => ({
  searchHits: vi.fn(async () => ([{
    conversation_id: 'c1', seq: 42, message_id: 'm1', preview: 'foo bar baz', highlights: [{ start: 4, length: 3 }], anchor: { conversation_id: 'c1', seq: 42 }
  }])),
}))

vi.mock('react-router-dom', async (orig) => {
  const mod = await orig()
  return {
    ...(mod as Record<string, unknown>),
    useNavigate: () => (path: string) => { (globalThis as { __lastNav?: string }).__lastNav = path },
  }
})

describe('Search page', () => {
  it('shows hits and navigates to anchor', async () => {
    // polyfill matchMedia for antd responsive
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    render(
      <MemoryRouter>
        <Search />
      </MemoryRouter>
    )
    const input = screen.getByPlaceholderText('输入关键词，回车搜索') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'bar' } })
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
    await waitFor(() => expect(screen.getByText(/会话: c1/)).toBeInTheDocument())
    fireEvent.click(screen.getByText(/会话: c1/))
    await waitFor(() => expect((globalThis as { __lastNav?: string }).__lastNav).toContain('/chat?cid=c1&seq=42'))
  })
})
