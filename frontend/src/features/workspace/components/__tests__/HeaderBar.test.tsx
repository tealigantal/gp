import { render, screen } from '@testing-library/react'
import { HeaderBar } from '../HeaderBar'
import type { HealthResponse } from '../../../../shared/contracts'

function health(overrides: Partial<HealthResponse['runtime']> = {}): HealthResponse {
  return {
    status: 'ok',
    trading_day: '20260513',
    book_version: 'daily_old',
    llm_ready: true,
    storage: {
      session_count: 1,
      transcript_count: 2,
      claim_count: 3,
    },
    runtime: {
      market_phase: 'POSTCLOSE_PENDING',
      data_provider: 'akshare',
      auto_update_service: 'gp-worker',
      auto_update_expected: true,
      worker_poll_interval_sec: 15,
      book_freshness: 'daily_only',
      publish_allowed: true,
      repair_status: 'idle',
      repair_stage: 'idle',
      daily_data_state: 'freshness_blocked',
      daily_status: 'freshness_blocked',
      daily_freshness_ready: false,
      daily_target_day: '2026-05-13',
      daily_target_mode: 'current_ready',
      daily_checked_count: 50,
      daily_stale_count: 1,
      daily_stale_symbols: ['002594'],
      daily_failed_symbols: [],
      clock_data_status: 'close_pending',
      artifact_stage: 'daily_plan',
      artifact_freshness: 'blocked',
      artifact_status: 'blocked',
      tradeability_state: 'no_trade',
      services: [],
      ...overrides,
    },
  }
}

it('uses daily_status instead of publish_allowed for the header state pill', () => {
  render(
    <HeaderBar
      sessionId="s1"
      onSessionIdChange={() => {}}
      onNewSession={() => {}}
      health={health()}
      sessions={[]}
    />,
  )

  expect(screen.getAllByText('日线未就绪').length).toBeGreaterThan(0)
  expect(screen.queryByText('今日日线已就绪')).not.toBeInTheDocument()
  expect(screen.queryByText('日线计划')).not.toBeInTheDocument()
})
