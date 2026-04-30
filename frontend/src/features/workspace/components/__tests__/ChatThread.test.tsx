import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { ChatThread } from '../ChatThread'
import type { CanonicalMessage, CanonicalRunArtifact, TranscriptEvent } from '../../../../shared/contracts'

function makeRun(): CanonicalRunArtifact {
  return {
    run_id: 'run_1',
    artifact_id: 'artifact_1',
    book_version: 'book_1',
    as_of: new Date().toISOString(),
    trading_day: '20260101',
    daybook_effective_day: '20260101',
    pulse_trade_day: '20260101',
    pulse_slot_at: '2026-01-01 14:35:00',
    market_phase: 'INTRADAY_PM',
    slot_status: 'OK',
    run_action: 'RECOMMEND',
    tradeable: true,
    publish_allowed: true,
    non_trading: false,
    status_reason: '当前有计划。',
    no_trade_reasons: [],
    recovery_conditions: [],
    themes: [],
    picks: [
      {
        symbol: '000001',
        code: '000001',
        name: '平安银行',
        rank: 1,
        action: 'BUY',
        execution_state: 'BUY_NOW',
        can_execute_now: true,
        thesis: '主线强势，价格仍在买点附近。',
        why_selected: '量价结构更完整。',
        entry_text: '10.20 - 10.35',
        stop_text: '9.98',
        take_text: '10.88',
        risk_level: 'medium_low',
        final_score: 0.92,
        live_score: 0.88,
        slot_rel_vol: 1.42,
        vwap: 10.26,
        entry_distance_pct: 0.003,
        data_provenance: { daily_last_date: '2026-01-01', daily_freshness_state: 'current' },
      },
      {
        symbol: '000002',
        code: '000002',
        name: '万科A',
        rank: 2,
        action: 'BUY',
        execution_state: 'WAIT_PULLBACK',
        can_execute_now: false,
        thesis: '逻辑还在，但已经偏离买点。',
        why_selected: '日级结构依然保留。',
        entry_text: '8.20 - 8.28',
        stop_text: '7.95',
        take_text: '8.70',
        risk_level: 'medium',
        final_score: 0.81,
        live_score: 0.74,
        data_provenance: { daily_last_date: '2026-01-01', daily_freshness_state: 'current' },
      },
    ],
    gate: {},
    data_quality: { complete: true },
    data_provenance: {},
    tool_trace: {},
  }
}

function assistantTurn(message: CanonicalMessage, opts: Partial<TranscriptEvent> = {}): TranscriptEvent {
  return {
    seq: 1,
    turn_id: 't1',
    session_id: 's1',
    role: 'assistant',
    content: 'stub',
    created_at: new Date().toISOString(),
    meta: { message, run_id: 'run_1' },
    ...opts,
  }
}

const baseProps: React.ComponentProps<typeof ChatThread> = {
  turns: [],
  error: null,
  sending: false,
  book: undefined,
  onPrompt: () => {},
}

it('renders recommendation picks with entry stop take and execution state', () => {
  const run = makeRun()
  const message: CanonicalMessage = {
    message_kind: 'recommend',
    narrative_text: '今天优先看 2 只。',
    picks: run.picks,
    run,
  }
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getByText(/10.20 - 10.35/)).toBeInTheDocument()
  expect(screen.getByText(/9.98/)).toBeInTheDocument()
  expect(screen.getByText(/10.88/)).toBeInTheDocument()
  expect(screen.getAllByText('现在可执行').length).toBeGreaterThan(0)
  expect(screen.getAllByText(/日线截止 2026-01-01/).length).toBeGreaterThan(0)
})

it('postclose recommend still renders recommendation card', () => {
  const run = { ...makeRun(), non_trading: true, publish_allowed: false, market_phase: 'POSTCLOSE_PENDING', run_action: 'DEGRADED' as const }
  const message: CanonicalMessage = {
    message_kind: 'recommend',
    narrative_text: '下一交易窗口计划。',
    picks: run.picks.map((pick) => ({ ...pick, execution_state: 'WAIT_NEXT_SESSION', can_execute_now: false })),
    run: {
      ...run,
      picks: run.picks.map((pick) => ({ ...pick, execution_state: 'WAIT_NEXT_SESSION', can_execute_now: false })),
    },
  }
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getByText('下一交易窗口计划。')).toBeInTheDocument()
  expect(screen.queryByText(/空仓 \/ 观察/)).toBeNull()
})

it('renders live entry card', () => {
  const message: CanonicalMessage = {
    message_kind: 'live_entry_check',
    narrative_text: '逻辑还在，但等回踩确认。',
    live_check: {
      symbol: '000001',
      execution_state: 'WAIT_PULLBACK',
      can_execute_now: false,
      next_action: '等回踩买入区再确认。',
      summary: '当前不适合追。',
      entry_text: '10.20 - 10.35',
      stop_text: '9.98',
      take_text: '10.88',
      vwap: 10.26,
      orb30_low: 10.1,
      orb30_high: 10.4,
    },
    run: makeRun(),
  }
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getAllByText(/等回踩确认/).length).toBeGreaterThan(0)
  expect(screen.getByText(/等回踩买入区再确认/)).toBeInTheDocument()
})

it('quick action click sends natural prompt', () => {
  const run = makeRun()
  const onPrompt = vi.fn()
  const message: CanonicalMessage = {
    message_kind: 'recommend',
    narrative_text: '今天优先看 2 只。',
    picks: run.picks,
    run,
  }
  render(<ChatThread {...baseProps} onPrompt={onPrompt} turns={[assistantTurn(message)]} />)
  fireEvent.click(screen.getAllByText('现在还能买吗')[0])
  expect(onPrompt).toHaveBeenCalled()
  expect(String(onPrompt.mock.calls[0][0])).toContain('000001')
})
