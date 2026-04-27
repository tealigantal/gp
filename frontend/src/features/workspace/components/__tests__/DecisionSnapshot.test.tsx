import { render, screen } from '@testing-library/react'
import { DecisionSnapshot } from '../DecisionSnapshot'
import type { ChatResponse, HealthResponse, MarketBook, SessionResponse } from '../../../../shared/contracts'

function bookWithFallback(): MarketBook {
  return {
    trading_day: '20260101',
    book_version: 'book_fallback',
    artifact_id: 'artifact_fallback',
    slot_status: 'DEGRADED',
    publish_allowed: false,
    updated_at: new Date().toISOString(),
    regime: {},
    daybook: {
      trading_day: '20260101',
      generated_at: new Date().toISOString(),
      regime: {},
      tradeable: true,
      themes: [],
      picks: [],
      reserve_symbols: [],
      source_meta: {},
    },
    board: [],
    watchset: [],
    symbol_states: {},
    portfolio_snapshot: {},
    last_closed_5m: null,
    side_results: [],
    market_phase: 'POSTCLOSE_PENDING',
  }
}

const health: HealthResponse = {
  status: 'ok',
  trading_day: '20260101',
  book_version: 'book_fallback',
  llm_ready: true,
  storage: {
    session_count: 2,
    transcript_count: 8,
    claim_count: 3,
  },
  runtime: {
    market_phase: 'POSTCLOSE_PENDING',
    data_provider: 'akshare',
    auto_update_service: 'gp-worker',
    auto_update_expected: true,
    worker_poll_interval_sec: 15,
    book_freshness: 'postclose_ready',
    book_updated_at: new Date().toISOString(),
    last_closed_5m: '2026-01-01 14:55:00',
    slot_status: 'DEGRADED',
    publish_allowed: false,
    daily_freshness_ready: true,
    daily_target_day: '2026-01-01',
    daily_checked_count: 3,
    daily_stale_count: 0,
    daily_failed_symbols: [],
    services: [
      {
        service: 'gp-worker',
        mode: 'always_on',
        command: 'python -m gp_assistant.cli pulse-loop',
        description: 'worker',
      },
      {
        service: 'gp-replay-today',
        mode: 'manual',
        profile: 'ops',
        command: 'python -m gp_assistant.cli replay-today',
        description: 'replay',
      },
    ],
  },
}

const session: SessionResponse = {
  session: {
    session_id: 's1',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    focus_subject: {},
    compare_set: [],
    user_preferences: {},
    last_claim_ids: [],
  },
  recent_turns: [],
  recent_claims: [],
}

it('uses the same run_id and artifact_id from latest message snapshot', () => {
  const latest: ChatResponse = {
    session_id: 's1',
    reply: 'ok',
    run_id: 'run_123',
    symbols: ['AAA'],
    message: {
      message_kind: 'recommend',
      narrative_text: 'ok',
      picks: [],
      run: {
        run_id: 'run_123',
        artifact_id: 'artifact_123',
        book_version: 'book_123',
        as_of: new Date().toISOString(),
        trading_day: '20260101',
        run_action: 'DEGRADED',
        tradeable: true,
        publish_allowed: false,
        non_trading: true,
        no_trade_reasons: [],
        recovery_conditions: [],
        themes: [],
        picks: [],
        gate: {},
        data_quality: { complete: true },
        data_provenance: {},
        tool_trace: {},
      },
    },
    right_panel: {},
    ui_items: [],
    planner_trace: {},
    evidence_refs: [],
  }
  render(<DecisionSnapshot book={bookWithFallback()} session={session} latest={latest} health={health} />)
  expect(screen.getByText(/run_123/)).toBeInTheDocument()
  expect(screen.getByText(/artifact_123/)).toBeInTheDocument()
})

it('shows next-session wording for postclose plans', () => {
  const latest: ChatResponse = {
    session_id: 's1',
    reply: 'ok',
    run_id: 'run_123',
    symbols: [],
    message: {
      message_kind: 'recommend',
      narrative_text: 'ok',
      picks: [],
      run: {
        run_id: 'run_123',
        artifact_id: 'artifact_123',
        as_of: new Date().toISOString(),
        trading_day: '20260101',
        run_action: 'DEGRADED',
        tradeable: true,
        publish_allowed: false,
        non_trading: true,
        no_trade_reasons: [],
        recovery_conditions: [],
        themes: [],
        picks: [],
        gate: {},
        data_quality: { complete: false },
        data_provenance: {},
        tool_trace: {},
      },
    },
    right_panel: {},
    ui_items: [],
    planner_trace: {},
    evidence_refs: [],
  }
  render(<DecisionSnapshot book={bookWithFallback()} session={session} latest={latest} health={health} />)
  expect(screen.getByText('下一交易窗口计划')).toBeInTheDocument()
})

it('shows runtime tools from health status', () => {
  render(<DecisionSnapshot book={bookWithFallback()} session={session} latest={null} health={health} />)
  expect(screen.getByText('运行与工具')).toBeInTheDocument()
  expect(screen.getByText('gp-worker')).toBeInTheDocument()
  expect(screen.getByText('gp-replay-today')).toBeInTheDocument()
})
