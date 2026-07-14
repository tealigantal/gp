import { describe, expect, it } from 'vitest'
import type { HealthResponse } from '../../shared/contracts'
import { deriveWorkspaceReadiness } from './readiness'

function health(overrides: Partial<HealthResponse> = {}): HealthResponse {
  return {
    status: 'degraded',
    product_ready: false,
    readiness_reasons: ['LLM 尚未通过真实调用验证：unverified'],
    agent_db: { sessions: 0, turns: 0, snapshots: 1, path: '/store/agent.db' },
    current_snapshot: {
      snapshot_id: 'snapshot-native', schema_version: 'RecommendationSnapshot.v1',
      as_of: '2026-07-14T16:00:00+08:00', decision: 'recommend', tradeable: false,
      payload_hash: 'hash',
    },
    history_db: { path: '/store/history.db', exists: true, bytes: 1 },
    llm: {
      available: true, configured: true, configuration_reason: 'ok',
      verification: 'unverified', model: 'deepseek-v4-flash',
    },
    serenity: {
      available: true, reason: 'ok', snapshot_native_ready: true,
      snapshot_target_id: 'target-1', candidate_target: { target_id: 'target-1' },
    },
    worker: {
      publisher: 'RecommendationSnapshot.v1',
      selection_policy: 'adaptive_v2_native_serenity_single_score',
      runtime_contract_ready: true,
    },
    ...overrides,
  }
}

describe('workspace product readiness', () => {
  it('allows the first real LLM turn only after native Alpha and market time are ready', () => {
    const readiness = deriveWorkspaceReadiness(health())
    expect(readiness.canChat).toBe(true)
    expect(readiness.statusLabel).toBe('等待首次 LLM 验证')
  })

  it('blocks old or incomplete snapshots and exposes the real reason', () => {
    const readiness = deriveWorkspaceReadiness(health({
      readiness_reasons: ['Serenity 原生 Alpha 未就绪：candidate_target_unavailable'],
      serenity: {
        available: false, reason: 'candidate_target_unavailable',
        snapshot_native_ready: false, snapshot_target_id: null, candidate_target: null,
      },
      worker: {
        publisher: 'RecommendationSnapshot.v1',
        selection_policy: 'adaptive_v2_native_serenity_single_score',
        runtime_contract_ready: false,
      },
    }))
    expect(readiness.canChat).toBe(false)
    expect(readiness.noticeDescription).toContain('candidate_target_unavailable')
  })

  it('does not deadlock retries after a real LLM transport error', () => {
    const readiness = deriveWorkspaceReadiness(health({
      readiness_reasons: ['LLM 尚未通过真实调用验证：error'],
      llm: {
        available: false, configured: true, configuration_reason: 'ok',
        verification: 'error', model: 'deepseek-v4-flash',
      },
    }))
    expect(readiness.canChat).toBe(true)
    expect(readiness.statusLabel).toBe('等待 LLM 重新验证')
  })

  it('blocks chat when the provider is not configured', () => {
    const readiness = deriveWorkspaceReadiness(health({
      readiness_reasons: ['LLM 尚未通过真实调用验证：not_configured'],
      llm: {
        available: false, configured: false, configuration_reason: 'missing_api_key',
        verification: 'not_configured', model: 'deepseek-v4-flash',
      },
    }))
    expect(readiness.canChat).toBe(false)
    expect(readiness.noticeDescription).toContain('真实 LLM 未配置')
  })
})
