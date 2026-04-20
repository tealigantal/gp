import { render, screen } from '@testing-library/react'
import React from 'react'
import { DecisionSnapshot } from '../DecisionSnapshot'
import type { ChatResponse, MarketBook, SessionResponse } from '../../../../shared/contracts'

function bookWithTop(symbols: string[]): MarketBook {
  return {
    trading_day: '20260101',
    book_version: 'v1',
    updated_at: new Date().toISOString(),
    regime: {},
    daybook: { trading_day: '20260101', generated_at: new Date().toISOString(), regime: {}, tradeable: false, themes: [], picks: [], reserve_symbols: [], source_meta: {} },
    board: symbols.map((s, i) => ({ symbol: s, name: s, rank: i + 1, final_score: 1, live_score: 1, execution_state: 'watch', can_open: false, stretched: false, invalidated: false, summary: '', pick: { symbol: s, rank: i + 1, thesis: '', entry_plan: {}, stop_plan: {}, take_profit_plan: {}, scores: {}, risk_flags: [], why_selected: '', why_not_others: [], evidence_refs: [] } } as any)),
    watchset: [],
    symbol_states: {},
    portfolio_snapshot: {},
    last_closed_5m: null,
    side_results: [],
  }
}

const session: SessionResponse = { session: { session_id: 's1', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), focus_subject: {}, compare_set: [], user_preferences: {}, last_claim_ids: [] }, recent_turns: [], recent_claims: [] }

it('prefers latest.right_panel.top3 over book.board', () => {
  const latest: ChatResponse = {
    session_id: 's1',
    reply: 'ok',
    message: undefined as any,
    run_id: null,
    symbols: [],
    right_panel: { top3: [{ symbol: 'AAA', rank: 1, action: 'BUY', state_label: '当前可买' }, { symbol: 'BBB', rank: 2, action: 'WATCH', state_label: '观察' }] },
    ui_items: [],
    planner_trace: {},
    evidence_refs: [],
  }
  render(<DecisionSnapshot book={bookWithTop(['000001', '000002'])} session={session} latest={latest} />)
  expect(screen.getAllByText(/AAA/).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/BBB/).length).toBeGreaterThan(0)
  // should not show board symbols when latest is present
  expect(screen.queryByText(/000001/)).toBeNull()
})

