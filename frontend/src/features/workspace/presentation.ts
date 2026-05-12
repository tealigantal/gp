import type { CanonicalRunArtifact, MarketBook, RuntimeStatus } from '../../shared/contracts'

export interface ToneMeta {
  color: string
  label: string
  hint?: string
}

export function isIntradayEnabled(runtime?: RuntimeStatus | null) {
  void runtime
  return false
}

export function recommendationStateMeta(state?: string | null): ToneMeta {
  const mapping: Record<string, ToneMeta> = {
    TRADING_SIGNAL: { color: 'green', label: '交易信号', hint: '当前有可执行交易信号。' },
    TRIGGER_PLAN: { color: 'gold', label: '等待触发', hint: '当前没有直接交易信号，等待触发价。' },
    NEXT_SESSION_PLAN: { color: 'blue', label: '下个交易窗口', hint: '当前不是即时交易窗口。' },
    NO_TRADE: { color: 'default', label: '无交易计划', hint: '当前没有合格交易计划。' },
    UNAVAILABLE: { color: 'default', label: '数据不足', hint: '真实数据不足，无法判断。' },
  }
  return mapping[String(state || '').toUpperCase()] || { color: 'default', label: state || '--' }
}

export function executionStateMeta(state?: string | null): ToneMeta {
  const mapping: Record<string, ToneMeta> = {
    TRADING_SIGNAL: { color: 'green', label: '交易信号', hint: '当前有可执行交易信号。' },
    TRIGGER_PLAN: { color: 'gold', label: '等待触发', hint: '当前没有直接交易信号，等待触发价。' },
    NEXT_SESSION_PLAN: { color: 'blue', label: '下个交易窗口', hint: '当前不是即时交易窗口。' },
    NO_TRADE: { color: 'default', label: '无交易计划', hint: '当前没有合格交易计划。' },
    WAITING_TRIGGER: { color: 'gold', label: '等待触发', hint: '策略条件存在，但还没有触发。' },
    TREND_CONTINUATION_BUY: { color: 'green', label: '趋势延续', hint: '趋势延续策略已触发。' },
    BREAKOUT_BUY: { color: 'green', label: '突破确认', hint: '突破策略已触发。' },
    RECLAIM_BUY: { color: 'green', label: '修复确认', hint: '回踩修复策略已触发。' },
    AFTERNOON_RELAUNCH_BUY: { color: 'green', label: '午后再启动', hint: '午后再启动策略已触发。' },
    GATE_BLOCKED: { color: 'volcano', label: '风控拦截', hint: '市场或风控 gate 不允许开仓。' },
    GATE_UNAVAILABLE: { color: 'default', label: '数据不足', hint: 'gate 数据不足，不能开仓。' },
    OBSERVE: { color: 'default', label: '无交易计划', hint: '当前没有合格交易计划。' },
    EXTENDED: { color: 'volcano', label: '追高风险', hint: '价格过度拉伸，不适合直接追。' },
    PLAN_READY: { color: 'green', label: '计划区间内', hint: '价格处在日线计划区间内。' },
    BUY_NOW: { color: 'green', label: '计划区间内', hint: '价格处在日线计划区间内。' },
    WAIT_PULLBACK: { color: 'gold', label: '等回踩', hint: '逻辑仍在，但不适合追高。' },
    WAIT_NEXT_SESSION: { color: 'gold', label: '等回踩', hint: '按日线计划等待更合适的位置。' },
    WATCH_ONLY: { color: 'default', label: '暂不入场', hint: '当前不主动追价。' },
    RISK_HIGH: { color: 'volcano', label: '风险偏高', hint: '位置或风险收益比不够理想。' },
    INVALIDATED: { color: 'red', label: '计划失效', hint: '已触发失效条件，不再按原计划处理。' },
    UNAVAILABLE: { color: 'default', label: '暂不入场', hint: '当前缺少正式日线计划条件。' },
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
    TRADING_SIGNAL: '交易信号',
    TRIGGER_PLAN: '等待触发',
    NEXT_SESSION_PLAN: '下个交易窗口',
    UNAVAILABLE: '数据不足',
    NO_TRADE: '无交易计划',
    RECOMMEND: '日线计划',
    DEGRADED: '数据受限',
  }
  return mapping[String(action || '').toUpperCase()] || action || '--'
}

export function slotStatusLabel(status?: string | null) {
  const mapping: Record<string, string> = {
    OK: '日线就绪',
    DEGRADED: '数据受限',
    UNAVAILABLE: '暂不可用',
  }
  return mapping[String(status || '').toUpperCase()] || status || '--'
}

export function runStateMeta(
  run?: CanonicalRunArtifact | null,
  opts?: { book?: MarketBook; runtime?: RuntimeStatus | null },
): { badge: ToneMeta; title: string; summary: string } {
  const book = opts?.book

  if (!run) {
    return {
      badge: { color: 'default', label: '等待提问' },
      title: '可以直接询问今天的候选、入选原因、买入区和风控边界。',
      summary: '当前系统只使用日线计划链路。',
    }
  }

  const recommendationState = String(run.recommendation_state || '').toUpperCase()
  if (recommendationState === 'TRADING_SIGNAL') {
    return {
      badge: recommendationStateMeta(recommendationState),
      title: '当前有可执行交易信号。',
      summary: run.status_reason || '每只票都应按计算层给出的触发价、买入区间、止损、止盈和有效窗口执行。',
    }
  }

  if (recommendationState === 'TRIGGER_PLAN') {
    return {
      badge: recommendationStateMeta(recommendationState),
      title: '当前没有直接交易信号，下面是等待触发的交易计划。',
      summary: run.status_reason || '不能直接买入，需要等待明确 trigger 和策略确认条件。',
    }
  }

  if (recommendationState === 'NEXT_SESSION_PLAN') {
    return {
      badge: recommendationStateMeta(recommendationState),
      title: '当前不是即时交易窗口，以下是下一交易窗口策略计划。',
      summary: run.status_reason || '非交易时段只展示下一交易窗口计划，不能表达为可立即执行。',
    }
  }

  if (recommendationState === 'NO_TRADE') {
    return {
      badge: recommendationStateMeta(recommendationState),
      title: '当前没有合格交易计划。',
      summary: run.status_reason || '策略、RR、风控或市场状态不支持开仓。',
    }
  }

  if (recommendationState === 'UNAVAILABLE') {
    return {
      badge: recommendationStateMeta(recommendationState),
      title: '真实数据不足，无法判断。',
      summary: run.status_reason || '需要等待数据补齐后再生成计划。',
    }
  }

  if (run.run_action === 'NO_TRADE') {
    return {
      badge: { color: 'default', label: '暂不入场' },
      title: '今天先不硬做，等待更清晰的日线机会。',
      summary: run.status_reason || '当前条件不足以支持主动开仓。',
    }
  }

  if (run.run_action === 'DEGRADED') {
    return {
      badge: { color: 'gold', label: '数据受限' },
      title: '日线计划数据不够完整，先降低执行强度。',
      summary: run.status_reason || '等日线数据恢复完整后再推进。',
    }
  }

  if (run.run_action === 'RECOMMEND') {
    return {
      badge: { color: 'green', label: '日线计划' },
      title: '当前有可跟踪的日线计划。',
      summary: run.status_reason || '重点看买入区、失效位、止盈位和风险收益比。',
    }
  }

  if (book?.publish_allowed) {
    return {
      badge: { color: 'green', label: '日线计划' },
      title: '当前可以沿着日线计划继续处理。',
      summary: '优先看买入区、失效位和是否出现新的追高风险。',
    }
  }

  return {
    badge: { color: 'default', label: '暂不入场' },
    title: '当前暂不入场，等待条件重新满足。',
    summary: run.status_reason || '可以继续追问为什么这样判断，或者什么条件下结论会变化。',
  }
}
