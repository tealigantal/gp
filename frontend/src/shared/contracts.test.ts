import { describe, expect, it } from 'vitest'
import type { ChatRequest, ChatResponse } from './contracts'

describe('single chat contract', () => {
  it('requires a client turn identity and a snapshot-bound response', () => {
    const request: ChatRequest = { message: '推荐一下', client_turn_id: 'turn-1' }
    const response: ChatResponse = { session_id: 'session-1', client_turn_id: request.client_turn_id, snapshot_id: 'snapshot-1', decision: 'recommend', reply: '当前快照结果', message: {}, symbols: ['600519'] }
    expect(response.snapshot_id).toBe('snapshot-1')
  })
})
