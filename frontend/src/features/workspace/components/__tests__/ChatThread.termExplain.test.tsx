import { render, screen } from '@testing-library/react'
import type { CanonicalMessage, TranscriptEvent } from '../../../../shared/contracts'
import { ChatThread } from '../ChatThread'

function assistantTurn(message: CanonicalMessage): TranscriptEvent {
  return {
    seq: 1,
    turn_id: 't1',
    session_id: 's1',
    role: 'assistant',
    content: 'stub',
    created_at: new Date().toISOString(),
    meta: { message },
  }
}

it('renders term explain followup text', () => {
  const message: CanonicalMessage = {
    message_kind: 'term_explain',
    narrative_text: '“收盘有效跌破支撑带”是在解释风控边界，不是盘中一下跌破就立刻追着卖。',
    followup_suggestions: ['这只现在还能买吗'],
  }
  render(<ChatThread turns={[assistantTurn(message)]} error={null} sending={false} book={undefined} onPrompt={() => {}} />)
  expect(screen.getByText(/风控边界/)).toBeInTheDocument()
  expect(screen.getByText('这只现在还能买吗')).toBeInTheDocument()
})
