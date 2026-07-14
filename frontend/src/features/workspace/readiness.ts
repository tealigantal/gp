import type { HealthResponse } from '../../shared/contracts'

const LLM_VERIFICATION_PREFIX = 'LLM 尚未通过真实调用验证：'

export interface WorkspaceReadiness {
  canChat: boolean
  blockingReasons: string[]
  statusLabel: string
  statusColor: string
  noticeTitle?: string
  noticeDescription?: string
  noticeType?: 'info' | 'warning'
}

export function deriveWorkspaceReadiness(health?: HealthResponse): WorkspaceReadiness {
  if (!health) {
    return {
      canChat: false,
      blockingReasons: ['正在读取荐股链路状态'],
      statusLabel: '正在检查链路',
      statusColor: 'default',
      noticeTitle: '正在读取荐股链路状态',
      noticeType: 'info',
    }
  }

  const nonLlmReasons = health.readiness_reasons.filter(
    (reason) => !reason.startsWith(LLM_VERIFICATION_PREFIX),
  )
  const nativeReady = Boolean(
    health.current_snapshot
    && health.serenity.available
    && health.serenity.snapshot_native_ready
    && health.worker.runtime_contract_ready,
  )
  const blockingReasons = [...nonLlmReasons]

  if (!health.llm.configured) {
    blockingReasons.push(`真实 LLM 未配置：${health.llm.configuration_reason || '缺少可用配置'}`)
  }
  if (!nativeReady && blockingReasons.length === 0) {
    blockingReasons.push('当前推荐快照或 Serenity 原生 Alpha 尚未就绪')
  }

  const canChat = nativeReady && health.llm.configured && blockingReasons.length === 0
  if (health.product_ready) {
    return {
      canChat: true,
      blockingReasons: [],
      statusLabel: health.current_snapshot?.tradeable ? '当前快照可交易' : '当前无交易计划',
      statusColor: health.current_snapshot?.tradeable ? 'green' : 'blue',
    }
  }
  if (canChat) {
    const firstVerification = health.llm.verification === 'unverified'
    return {
      canChat: true,
      blockingReasons: [],
      statusLabel: firstVerification ? '等待首次 LLM 验证' : '等待 LLM 重新验证',
      statusColor: 'gold',
      noticeTitle: '荐股快照与 Serenity Alpha 已就绪',
      noticeDescription: firstVerification
        ? '首次提问将通过真实 LLM 完成意图路由与证据解释。'
        : '下一次提问将重新验证真实 LLM 的完整两阶段调用。',
      noticeType: 'info',
    }
  }

  return {
    canChat: false,
    blockingReasons,
    statusLabel: '荐股链路未就绪',
    statusColor: 'orange',
    noticeTitle: '荐股链路尚未就绪',
    noticeDescription: blockingReasons.join('；'),
    noticeType: 'warning',
  }
}
