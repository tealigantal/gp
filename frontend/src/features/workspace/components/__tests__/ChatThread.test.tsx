import { render, screen } from '@testing-library/react'
import React from 'react'
import { ChatThread } from '../ChatThread'
import type { CanonicalMessage, TranscriptEvent } from '../../../../shared/contracts'

function assistantTurn(message: CanonicalMessage, opts: Partial<TranscriptEvent> = {}): TranscriptEvent {
  return {
    seq: 1,
    turn_id: 't1',
    session_id: 's1',
    role: 'assistant',
    content: 'stub',
    created_at: new Date().toISOString(),
    meta: { message },
    ...opts,
  }
}

const baseProps = {
  turns: [] as TranscriptEvent[],
  latestResponse: null as any,
  error: null,
  sending: false,
  book: undefined,
  onPrompt: () => {},
}

it('renders recommend picks', () => {
  const message: CanonicalMessage = {
    message_kind: 'recommend',
    narrative_text: 'n',
    picks: [
      { symbol: '000001', rank: 1, action: 'WATCH', state_label: '观察' },
      { symbol: '000002', rank: 2, action: 'BUY', state_label: '当前可买' },
    ] as any,
  } as any
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getAllByText(/000001/).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/000002/).length).toBeGreaterThan(0)
})

it('renders exit decision card', () => {
  const message: CanonicalMessage = {
    message_kind: 'exit',
    narrative_text: '请谨慎',
    symbol: '600519',
  } as any
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getAllByText('卖出判断').length).toBeGreaterThan(0)
  expect(screen.getByText('600519')).toBeInTheDocument()
})

it('renders run_change card', () => {
  const message: CanonicalMessage = {
    message_kind: 'run_change',
    narrative_text: '对比结果',
  } as any
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} />)
  expect(screen.getByText('对比结果')).toBeInTheDocument()
})

it('renders chat suggestions', () => {
  const message: CanonicalMessage = {
    message_kind: 'chat',
    narrative_text: '你好',
    followup_suggestions: ['今天给我 3 只'],
  } as any
  render(<ChatThread {...baseProps} turns={[assistantTurn(message)]} onPrompt={() => {}} />)
  expect(screen.getByText('今天给我 3 只')).toBeInTheDocument()
})





