import type { RuntimeStatus } from '../../shared/contracts'

export function fmtDateTime(value?: string | null) {
  if (!value) return '--'
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return value
  return dt.toLocaleString('zh-CN', { hour12: false })
}

export function marketPhaseLabel(phase?: string | null) {
  const mapping: Record<string, string> = {
    NON_TRADING: '非交易时段',
    PREOPEN: '盘前准备',
    OPEN_NO_FIRST_BAR: '开盘等待首个 5 分钟',
    INTRADAY_AM: '盘中上午',
    LUNCH_BREAK: '午间休市',
    INTRADAY_PM: '盘中下午',
    CLOSING_AUCTION: '收盘集合竞价',
    POSTCLOSE_PENDING: '收盘后计划阶段',
    POSTCLOSE_READY: '收盘后已归档',
  }
  return mapping[String(phase || '').toUpperCase()] || phase || '--'
}

export function dailyTargetModeMeta(runtime?: RuntimeStatus | null) {
  const mode = String(runtime?.daily_target_mode || '').toLowerCase()
  if (mode === 'previous_completed') {
    return {
      label: '使用上一已完成日线',
      color: 'blue',
      note: `日线目标为 ${runtime?.daily_target_day || '--'}，这是盘中正式口径，不属于故障。`,
    }
  }
  if (mode === 'current_pending') {
    const retry = runtime?.eod_probe?.next_retry_after ? `下次探测 ${fmtDateTime(runtime.eod_probe.next_retry_after)}。` : ''
    return {
      label: '等待今日收盘日线',
      color: 'gold',
      note: `今日 ${runtime?.pending_eod_day || runtime?.daily_target_day || '--'} 收盘日线尚未确认，worker 会自动重试。${retry}`,
    }
  }
  if (mode === 'current_ready') {
    return {
      label: '今日日线已就绪',
      color: 'green',
      note: `日线目标 ${runtime?.daily_target_day || '--'} 已就绪，可用于正式计划。`,
    }
  }
  return null
}

export function runtimeFreshnessMeta(runtime?: RuntimeStatus | null) {
  const dailyMode = dailyTargetModeMeta(runtime)
  if (dailyMode) return dailyMode
  if (runtime?.intraday_runtime_enabled === false) {
    return {
      label: '5 分钟执行态已停用',
      color: 'default',
      note: '当前运行态只保留日级计划与观察结论，不再接入盘中 5 分钟执行数据。',
    }
  }
  const key = String(runtime?.book_freshness || '').toLowerCase()
  const mapping: Record<string, { label: string; color: string; note: string }> = {
    current: {
      label: '已对齐最新 slot',
      color: 'green',
      note: '当前 book 已对齐到目标 5 分钟 slot，可以按最新执行状态解读。',
    },
    postclose_ready: {
      label: '收盘后计划已就绪',
      color: 'blue',
      note: '现在是收盘后计划视图，等下一交易窗口再做 5 分钟执行确认。',
    },
    awaiting_first_slot: {
      label: '等待首个 5 分钟',
      color: 'gold',
      note: '还没有形成首个已收盘 5 分钟 bar，先保留盘前计划。',
    },
    lagging: {
      label: 'book 落后于目标 slot',
      color: 'volcano',
      note: 'worker 应继续补齐最新 5 分钟状态；如果持续不恢复，再手动修复。',
    },
    degraded: {
      label: '执行数据降级',
      color: 'gold',
      note: '日级计划仍有效，但盘中执行数据不完整，先按降级语气解读。',
    },
    non_trading: {
      label: '非交易时段',
      color: 'blue',
      note: '当前不判断立刻成交，只保留下一交易窗口计划。',
    },
    available: {
      label: 'book 可读',
      color: 'default',
      note: '当前 book 可用，但未必已经对齐到最新 slot。',
    },
    unavailable: {
      label: '当前没有可用 book',
      color: 'default',
      note: '当前还没有有效的 book 或 slot artifact，需要等待 worker 自愈或手工修复。',
    },
  }
  return (
    mapping[key] || {
      label: runtime?.book_freshness || '--',
      color: 'default',
      note: '当前运行状态还没有映射成更具体的用户提示。',
    }
  )
}
