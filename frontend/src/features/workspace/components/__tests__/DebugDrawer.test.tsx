import { fireEvent, render, screen } from '@testing-library/react'
import { DebugDrawer } from '../DebugDrawer'
import type { ChatResponse, SessionDiagnosticsResponse, SessionResponse } from '../../../../shared/contracts'

const session: SessionResponse = {
  session: {
    session_id: 's1',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    active_run_id: 'run_live',
    previous_run_id: 'run_prev',
    focus_subject: {},
    compare_set: [],
    user_preferences: {},
    last_claim_ids: [],
    last_seen_book_version: 'book_1',
  },
  recent_turns: [],
  recent_claims: [],
}

const diagnostics: SessionDiagnosticsResponse = {
  session_id: 's1',
  focus: {
    active_run_id: 'run_live',
    previous_run_id: 'run_prev',
    last_focus_symbol: '000001',
    last_focus_rank: 1,
    compare_set: ['000001', '000002'],
  },
  latest_assistant: {
    turn_id: 't2',
    seq: 2,
    created_at: new Date().toISOString(),
    message_kind: 'term_explain',
    narrative_text: '收盘有效跌破支撑带，意思是收盘后确认失守关键支撑区域。',
    symbol: '000001',
    run_action: 'NO_TRADE',
    followup_suggestions: ['这只现在还能买吗'],
  },
  assistant_messages: [
    {
      turn_id: 't2',
      seq: 2,
      created_at: new Date().toISOString(),
      message_kind: 'term_explain',
      narrative_text: '收盘有效跌破支撑带，意思是收盘后确认失守关键支撑区域。',
      symbol: '000001',
      run_action: 'NO_TRADE',
      followup_suggestions: ['这只现在还能买吗'],
    },
  ],
}

const latestResponse: ChatResponse = {
  session_id: 's1',
  reply: 'ok',
  run_id: 'run_live',
  symbols: ['000001'],
  right_panel: {},
  ui_items: [],
  grounding_summary: {
    market_phase: 'INTRADAY_PM',
    daily_target_day: '2026-04-29',
    pulse_slot_at: '2026-04-29 14:35:00',
    repair_status: 'ready',
    decision_basis_labels: ['session memory'],
  },
}

it('renders safe diagnostics and latest assistant summaries', async () => {
  render(<DebugDrawer session={session} diagnostics={diagnostics} latestResponse={latestResponse} />)
  fireEvent.click(screen.getByText('Diagnostics / Session Truth'))
  expect(await screen.findByText('Safe Diagnostics')).toBeInTheDocument()
  expect(screen.getAllByText('000001').length).toBeGreaterThan(0)
  expect(screen.getByText('term_explain')).toBeInTheDocument()
  expect(screen.getByText(/收盘有效跌破支撑带/)).toBeInTheDocument()
  expect(screen.queryByText(/tool_trace/)).toBeNull()
})
