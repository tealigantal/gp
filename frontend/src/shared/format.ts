import dayjs from 'dayjs'

export function fmtTime(value?: string | null) {
  if (!value) return '--'
  return dayjs(value).format('MM-DD HH:mm:ss')
}

export function fmtNum(value?: number | null, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(value)) return '--'
  return Number(value).toFixed(digits)
}

export function fmtPct(value?: number | null, digits = 1) {
  if (value === undefined || value === null || Number.isNaN(value)) return '--'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function compactJson(value: unknown) {
  if (!value || (typeof value === 'object' && Object.keys(value as Record<string, unknown>).length === 0)) {
    return '--'
  }
  return JSON.stringify(value, null, 2)
}

export function tagColorByExecution(state?: string | null) {
  switch (String(state || '').toUpperCase()) {
    case 'PLAN_READY':
    case 'BUY_NOW':
      return 'green'
    case 'WAIT_PULLBACK':
      return 'gold'
    case 'WAIT_NEXT_SESSION':
      return 'blue'
    case 'RISK_HIGH':
      return 'volcano'
    default:
      return 'default'
  }
}
