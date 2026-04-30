import type { CanonicalRunArtifact, MarketBook, RuntimeStatus } from '../../shared/contracts'

export interface ToneMeta {
  color: string
  label: string
  hint?: string
}

export function isIntradayEnabled(runtime?: RuntimeStatus | null) {
  return runtime?.intraday_runtime_enabled !== false
}

export function executionStateMeta(state?: string | null): ToneMeta {
  const mapping: Record<string, ToneMeta> = {
    BUY_NOW: { color: 'green', label: '现在可执行', hint: '价格和结构都还在计划区内。' },
    WAIT_PULLBACK: { color: 'gold', label: '等回踩确认', hint: '逻辑还在，但不适合直接追高。' },
    WAIT_NEXT_SESSION: { color: 'blue', label: '留到下一窗口', hint: '先保留计划，下一交易窗口再确认。' },
    WATCH_ONLY: { color: 'default', label: '仅观察', hint: '当前先观察，不建议主动追价。' },
    RISK_HIGH: { color: 'volcano', label: '风险偏高', hint: '结构未坏，但风险收益比不够理想。' },
    INVALIDATED: { color: 'red', label: '计划失效', hint: '已触发失效条件，不再按原计划执行。' },
    UNAVAILABLE: { color: 'default', label: '执行数据降级', hint: '当前只能保留观察级判断。' },
  }
  return mapping[String(state || '').toUpperCase()] || { color: 'default', label: state || '--' }
}

export function riskLabel(level?: string | null) {
  const mapping: Record<string, string> = {
    low: '低',
    medium_low: '中低',
    medium: '中',
    medium_high: '中高',
    high: '高',
  }
  return mapping[String(level || '').toLowerCase()] || level || '--'
}

export function runActionLabel(action?: string | null) {
  const mapping: Record<string, string> = {
    RECOMMEND: '执行计划',
    DEGRADED: '降级观察',
    NO_TRADE: '空仓 / 观察',
  }
  return mapping[String(action || '').toUpperCase()] || action || '--'
}

export function slotStatusLabel(status?: string | null) {
  const mapping: Record<string, string> = {
    OK: '已对齐',
    DEGRADED: '数据降级',
    UNAVAILABLE: '暂不可用',
  }
  return mapping[String(status || '').toUpperCase()] || status || '--'
}

export function runStateMeta(
  run?: CanonicalRunArtifact | null,
  opts?: { book?: MarketBook; runtime?: RuntimeStatus | null },
): { badge: ToneMeta; title: string; summary: string } {
  const intradayEnabled = isIntradayEnabled(opts?.runtime)
  const book = opts?.book

  if (!run) {
    return {
      badge: { color: 'default', label: '等待提问' },
      title: '先用自然语言把问题抛给我，我会沿着同一条判断链继续回答。',
      summary: '可以直接问今天的候选、某只票为什么入选、现在还能不能买，或者为什么当前只观察。',
    }
  }

  if (!intradayEnabled) {
    if (run.run_action === 'NO_TRADE') {
      return {
        badge: { color: 'default', label: '日线观察' },
        title: '今天先不硬做，先保留日线观察结论。',
        summary: run.status_reason || '盘中 5 分钟执行数据已停用，当前只保留日线计划和风险边界。',
      }
    }
    return {
      badge: { color: 'blue', label: '日线模式' },
      title: '当前只提供日线计划和观察结论，不给 5 分钟级别的即时追单判断。',
      summary: run.status_reason || '你仍然可以继续追问逻辑、风险位和下一交易窗口计划。',
    }
  }

  if (run.run_action === 'NO_TRADE') {
    return {
      badge: { color: 'default', label: '空仓 / 观察' },
      title: '今天先不硬做，优先等更清晰的交易机会。',
      summary: run.status_reason || '当前市场和执行条件不足以支持强行开仓，先保留弹性。',
    }
  }

  if (run.non_trading) {
    return {
      badge: { color: 'blue', label: '下一交易窗口' },
      title: '现在先做盘后计划，不做“立刻买入”的盘中判断。',
      summary: run.status_reason || '等进入连续竞价或下一交易窗口后，再结合 5 分钟执行结构确认。',
    }
  }

  if (run.run_action === 'DEGRADED') {
    return {
      badge: { color: 'gold', label: '降级观察' },
      title: '今天有计划，但执行上要更克制，先确认再动手。',
      summary: run.status_reason || '环境偏弱或执行数据不完整，重点等买点回到计划区间附近。',
    }
  }

  if (run.run_action === 'RECOMMEND') {
    return {
      badge: { color: 'green', label: '执行计划' },
      title: '当前有可跟踪计划，优先按买点、失效位和执行结构来做。',
      summary: run.status_reason || '不要只看排名，真正决定能不能做的是价格位置、失效位和盘中确认。',
    }
  }

  if (book?.publish_allowed) {
    return {
      badge: { color: 'green', label: '执行计划' },
      title: '当前可以沿着计划继续跟踪执行。',
      summary: '优先看买入区、失效位和是否有新的追高风险。',
    }
  }

  return {
    badge: { color: 'default', label: '观察中' },
    title: '当前先保留观察，等信息更完整再推进。',
    summary: run.status_reason || '可以继续追问为什么这样判断，或者什么条件下结论会变化。',
  }
}
