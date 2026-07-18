import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'
import type { ChatResponse, HealthResponse } from '../../../shared/contracts'

const api = vi.hoisted(() => ({
  getHealth: vi.fn(),
  getCurrentBook: vi.fn(),
  getSession: vi.fn(),
  getSessionDiagnostics: vi.fn(),
  getSessions: vi.fn(),
  postChat: vi.fn(),
  runOpsTool: vi.fn(),
}))

vi.mock('../../../shared/api', () => ({
  ...api,
  readApiError: (error: unknown) => (error instanceof Error ? error.message : '请求失败'),
}))

import { useAdvisorWorkspace } from '../useAdvisorWorkspace'

function health(llmReady: boolean, llmRetryable: boolean): HealthResponse {
  return {
    status: llmReady ? 'ok' : 'degraded',
    llm_ready: llmReady,
    llm_retryable: llmRetryable,
    storage: { session_count: 0, transcript_count: 0, claim_count: 0 },
    runtime: {
      market_phase: 'NON_TRADING',
      data_provider: 'akshare',
      auto_update_service: 'gp-worker',
      auto_update_expected: true,
      worker_poll_interval_sec: 15,
      book_freshness: 'postclose_ready',
      publish_allowed: false,
      repair_status: 'idle',
      repair_stage: 'idle',
      artifact_status: 'ready',
      services: [],
    },
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
  api.getCurrentBook.mockResolvedValue({ book: {} })
  api.getSession.mockResolvedValue({
    session: {
      session_id: 'session_test',
      created_at: '2026-07-18T00:00:00+08:00',
      updated_at: '2026-07-18T00:00:00+08:00',
      focus_subject: {},
      compare_set: [],
      user_preferences: {},
      last_claim_ids: [],
    },
    recent_turns: [],
    recent_claims: [],
  })
  api.getSessionDiagnostics.mockResolvedValue({
    session_id: 'session_test',
    focus: { compare_set: [] },
    assistant_messages: [],
  })
  api.getSessions.mockResolvedValue([])
  api.postChat.mockResolvedValue({
    session_id: 'session_test',
    reply: '真实 LLM 已提交的回答',
    symbols: [],
    right_panel: {},
    ui_items: [],
    grounding_summary: { repair_status: 'idle', decision_basis_labels: [] },
  } satisfies ChatResponse)
})

it('refreshes health immediately after a real chat commits', async () => {
  api.getHealth
    .mockResolvedValueOnce(health(false, true))
    .mockResolvedValueOnce(health(true, true))

  const { result } = renderHook(() => useAdvisorWorkspace(), { wrapper })

  await waitFor(() => expect(result.current.health?.llm_retryable).toBe(true))
  expect(result.current.health?.llm_ready).toBe(false)

  await act(async () => {
    await result.current.submitMessage('请继续解释当前候选')
  })

  await waitFor(() => expect(api.getHealth).toHaveBeenCalledTimes(2))
  await waitFor(() => expect(result.current.health?.llm_ready).toBe(true))
})
