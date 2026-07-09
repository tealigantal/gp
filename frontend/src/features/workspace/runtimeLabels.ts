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
    OPEN_NO_FIRST_BAR: '开盘准备',
    INTRADAY_AM: '上午交易',
    LUNCH_BREAK: '午间休市',
    INTRADAY_PM: '下午交易',
    CLOSING_AUCTION: '收盘集合竞价',
    POSTCLOSE_PENDING: '收盘后计划阶段',
    POSTCLOSE_READY: '收盘后已归档',
  }
  return mapping[String(phase || '').toUpperCase()] || phase || '--'
}

export function dailyTargetModeMeta(runtime?: RuntimeStatus | null) {
  const mode = String(runtime?.daily_target_mode || '').toLowerCase()
  const blockedCurrentReady = mode === 'current_ready' && runtime?.daily_freshness_ready === false
  if (blockedCurrentReady) return null
  if (mode === 'previous_completed') {
    return {
      label: '使用上一已完成日线',
      color: 'blue',
      note: `日线目标为 ${runtime?.daily_target_day || '--'}。`,
    }
  }
  if (mode === 'current_pending') {
    const retry = runtime?.eod_probe?.next_retry_after ? `下次探测 ${fmtDateTime(runtime.eod_probe.next_retry_after)}。` : ''
    return {
      label: '等待今日收盘日线',
      color: 'gold',
      note: `今日 ${runtime?.pending_eod_day || runtime?.daily_target_day || '--'} 收盘日线尚未确认。${retry}`,
    }
  }
  if (mode === 'current_ready') {
    return {
      label: '今日日线已就绪',
      color: 'green',
      note: `日线目标 ${runtime?.daily_target_day || '--'} 已就绪。`,
    }
  }
  return null
}

export function dailyStatusMeta(runtime?: RuntimeStatus | null) {
  const explicit = String(runtime?.daily_data_state || runtime?.daily_status || '').toLowerCase()
  const artifactLagging =
    String(runtime?.artifact_freshness || '').toLowerCase() === 'lagging' ||
    (!runtime?.artifact_freshness && (explicit === 'artifact_lagging' || String(runtime?.book_freshness || '').toLowerCase() === 'lagging')) ||
    Boolean(runtime?.artifact_lag_reason)
  const eodPending = explicit === 'eod_pending' || runtime?.daily_target_mode === 'current_pending'
  const previousCompleted = explicit === 'previous_completed' || runtime?.daily_target_mode === 'previous_completed'
  const freshnessBlocked =
    explicit === 'freshness_blocked' || (runtime?.daily_freshness_ready === false && !eodPending && !previousCompleted)

  if (artifactLagging) {
    return {
      label: runtime?.market_phase === 'POSTCLOSE_PENDING' ? '日线已就绪，发布待归档' : '日线已就绪，发布待刷新',
      color: 'volcano',
      note: runtime?.artifact_lag_reason || '日线 freshness 已就绪，但 current artifact 仍落后于当前 daybook。',
    }
  }
  if (eodPending) {
    const retry = runtime?.eod_probe?.next_retry_after ? `下次探测 ${fmtDateTime(runtime.eod_probe.next_retry_after)}。` : ''
    return {
      label: '等待今日收盘日线',
      color: 'gold',
      note: `今日 ${runtime?.pending_eod_day || runtime?.daily_target_day || '--'} 收盘日线尚未确认。${retry}`,
    }
  }
  if (freshnessBlocked) {
    return {
      label: '日线未就绪',
      color: 'volcano',
      note: runtime?.daily_blocking_reason || `日线目标 ${runtime?.daily_target_day || '--'} 尚未完成全量 freshness 校验。`,
    }
  }
  if (explicit === 'ready' || runtime?.daily_target_mode === 'current_ready') {
    return {
      label: '今日日线已就绪',
      color: 'green',
      note: `日线目标 ${runtime?.daily_target_day || '--'} 已就绪。`,
    }
  }
  if (previousCompleted) {
    return {
      label: '使用上一已完成日线',
      color: 'blue',
      note: `日线目标为 ${runtime?.daily_target_day || '--'}。`,
    }
  }
  if (explicit === 'unavailable') {
    return {
      label: '暂无可用 book',
      color: 'default',
      note: '当前还没有有效的日线计划 book。',
    }
  }
  return null
}

export function runtimeFreshnessMeta(runtime?: RuntimeStatus | null) {
  const artifactFreshness = String(runtime?.artifact_freshness || '').toLowerCase()
  if (artifactFreshness === 'lagging') {
    return {
      label: runtime?.market_phase === 'POSTCLOSE_PENDING' ? '日线已就绪，发布待归档' : '发布待刷新',
      color: 'volcano',
      note: runtime?.artifact_lag_reason || '当前 artifact 落后于已确认的日线状态。',
    }
  }
  if (artifactFreshness === 'blocked') {
    return {
      label: '日线未就绪',
      color: 'volcano',
      note: runtime?.daily_blocking_reason || '日线 freshness 校验未通过。',
    }
  }
  const dailyStatus = dailyStatusMeta(runtime)
  if (dailyStatus) return dailyStatus
  const dailyMode = dailyTargetModeMeta(runtime)
  if (dailyMode) return dailyMode
  const key = String(runtime?.book_freshness || '').toLowerCase()
  const mapping: Record<string, { label: string; color: string; note: string }> = {
    current: {
      label: '日线计划已就绪',
      color: 'green',
      note: '当前 book 可用于日线计划解读。',
    },
    daily_only: {
      label: '日线模式',
      color: 'blue',
      note: '当前只使用日线计划链路。',
    },
    postclose_ready: {
      label: '收盘后计划已就绪',
      color: 'blue',
      note: '当前为收盘后计划视图。',
    },
    awaiting_first_slot: {
      label: '日线计划',
      color: 'blue',
      note: '当前只使用日线计划链路。',
    },
    lagging: {
      label: '等待日线更新',
      color: 'volcano',
      note: '后台应继续刷新日线计划。',
    },
    degraded: {
      label: '数据受限',
      color: 'gold',
      note: '日线计划数据不够完整。',
    },
    non_trading: {
      label: '非交易时段',
      color: 'blue',
      note: '当前仍可查看日线计划。',
    },
    available: {
      label: 'book 可读',
      color: 'default',
      note: '当前 book 可用于日线计划解读。',
    },
    unavailable: {
      label: '暂无可用 book',
      color: 'default',
      note: '当前还没有有效的日线计划 book。',
    },
  }
  return (
    mapping[key] || {
      label: runtime?.book_freshness || '--',
      color: 'default',
      note: '当前运行状态还没有映射成更具体的提示。',
    }
  )
}
