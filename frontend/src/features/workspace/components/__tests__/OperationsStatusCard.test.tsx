import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'
import { OperationsStatusCard } from '../OperationsStatusCard'
import type { OpsRunResponse, RuntimeStatus } from '../../../../shared/contracts'

function runtime(overrides: Partial<RuntimeStatus> = {}): RuntimeStatus {
  return {
    market_phase: 'POSTCLOSE_PENDING',
    data_provider: 'akshare',
    auto_update_service: 'gp-worker',
    auto_update_expected: true,
    worker_poll_interval_sec: 15,
    book_freshness: 'degraded',
    book_updated_at: '2026-01-01T15:01:00',
    artifact_id: 'artifact_1',
    daybook_effective_day: '20260101',
    pulse_trade_day: '20260101',
    pulse_slot_at: '2026-01-01 14:55:00',
    last_closed_5m: null,
    slot_status: 'UNAVAILABLE',
    publish_allowed: false,
    daily_freshness_ready: false,
    daily_target_day: '2026-01-01',
    daily_checked_count: 10,
    daily_stale_count: 2,
    daily_last_reconcile_at: '2026-01-01T15:00:00',
    daily_blocking_reason: '今天日线还没补齐到 2026-01-01，当前不发布正式推荐。',
    daily_failed_symbols: ['002716'],
    services: [
      {
        service: 'gp-worker',
        mode: 'always_on',
        command: 'python -m gp_assistant.cli pulse-loop',
        description: 'worker',
      },
      {
        service: 'gp-rebuild-daybook',
        mode: 'manual',
        profile: 'ops',
        command: 'python -m gp_assistant.cli rebuild-daybook',
        description: '重建当日 daybook',
      },
      {
        service: 'gp-replay-today',
        mode: 'manual',
        profile: 'ops',
        command: 'python -m gp_assistant.cli replay-today',
        description: '回放今日 slot',
      },
      {
        service: 'gp-postclose-archive',
        mode: 'manual',
        profile: 'ops',
        command: 'python -m gp_assistant.cli postclose-archive',
        description: '收盘归档',
      },
    ],
    ...overrides,
  }
}

it('renders clickable runtime tool buttons', () => {
  const onRunTool = vi.fn(async () => {})
  const onRefreshRuntime = vi.fn(async () => {})
  render(<OperationsStatusCard runtime={runtime()} onRunTool={onRunTool} onRefreshRuntime={onRefreshRuntime} />)

  fireEvent.click(screen.getByText('刷新状态'))
  fireEvent.click(screen.getAllByText('回放今日执行态')[0])

  expect(onRefreshRuntime).toHaveBeenCalled()
  expect(onRunTool).toHaveBeenCalledWith('gp-replay-today')
})

it.each([
  ['previous_completed', '使用上一已完成日线'],
  ['current_pending', '等待今日收盘日线'],
  ['current_ready', '今日日线已就绪'],
])('renders daily target mode %s', (mode, label) => {
  render(
    <OperationsStatusCard
      runtime={runtime({
        daily_freshness_ready: mode !== 'current_pending',
        daily_target_mode: mode,
        daily_target_day: mode === 'previous_completed' ? '2026-04-29' : '2026-04-30',
        pending_eod_day: mode === 'current_pending' ? '2026-04-30' : null,
        eod_probe: mode === 'current_pending' ? { ready: false, ok_count: 1, next_retry_after: '2026-04-30T15:10:00Z' } : null,
      })}
    />,
  )

  expect(screen.getAllByText(label).length).toBeGreaterThan(0)
})

it('does not promote rebuild daybook while eod daily is pending', () => {
  render(
    <OperationsStatusCard
      runtime={runtime({
        daily_freshness_ready: false,
        daily_target_mode: 'current_pending',
        pending_eod_day: '2026-04-30',
        eod_probe: { ready: false, ok_count: 1, next_retry_after: '2026-04-30T15:10:00Z' },
      })}
    />,
  )

  expect(screen.getByText('重建日线计划').closest('button')).not.toHaveClass('ant-btn-primary')
  expect(screen.getByText('等待日线')).toBeInTheDocument()
  expect(screen.getByText('EOD 探测')).toBeInTheDocument()
})

it('does not promote rebuild daybook for previous completed daily mode', () => {
  const { container } = render(
    <OperationsStatusCard
      runtime={runtime({
        daily_freshness_ready: false,
        daily_target_mode: 'previous_completed',
        daily_target_day: '2026-04-29',
      })}
    />,
  )

  const buttons = Array.from(container.querySelectorAll('button'))
  expect(buttons[1]).not.toHaveClass('ant-btn-primary')
})

it('shows operation feedback after a tool run', () => {
  const result: OpsRunResponse = {
    operation: 'gp-replay-today',
    status: 'ok',
    message: '已按当前时点回放今天已收盘的 5 分钟 slot。',
    executed_at: '2026-01-01T15:02:00',
    result: {
      trade_day: '20260101',
      replayed_slots: 8,
      current: {
        slot_status: 'DEGRADED',
        slot_at: '2026-01-01 14:55:00',
      },
    },
    runtime: runtime(),
  }

  render(<OperationsStatusCard runtime={runtime()} opsResult={result} />)

  expect(screen.getByText('已按当前时点回放今天已收盘的 5 分钟 slot。')).toBeInTheDocument()
  expect(screen.getByText(/已回放 8 个 slot/)).toBeInTheDocument()
  expect(screen.getByText(/日线未就绪/)).toBeInTheDocument()
})
