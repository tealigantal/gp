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
    book_freshness: 'daily_only',
    book_updated_at: '2026-01-01T15:01:00',
    artifact_id: 'artifact_1',
    daybook_effective_day: '20260101',
    pulse_trade_day: null,
    pulse_slot_at: null,
    last_closed_5m: null,
    slot_status: 'OK',
    publish_allowed: true,
    daily_data_state: 'freshness_blocked',
    daily_status: 'freshness_blocked',
    daily_freshness_ready: false,
    daily_target_day: '2026-01-01',
    daily_checked_count: 10,
    daily_stale_count: 2,
    daily_last_reconcile_at: '2026-01-01T15:00:00',
    daily_blocking_reason: '今天日线还没补齐到 2026-01-01，当前不发布正式推荐。',
    daily_failed_symbols: ['002716'],
    clock_data_status: 'close_pending',
    artifact_stage: 'daily_plan',
    artifact_freshness: 'blocked',
    artifact_status: 'blocked',
    tradeability_state: 'no_trade',
    services: [
      {
        service: 'gp-worker',
        mode: 'always_on',
        command: 'python -m gp_assistant.cli runtime-loop',
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
  fireEvent.click(screen.getAllByText('重建日线计划')[0])

  expect(onRefreshRuntime).toHaveBeenCalled()
  expect(onRunTool).toHaveBeenCalledWith('gp-rebuild-daybook')
})

it.each([
  ['previous_completed', 'previous_completed', '使用上一已完成日线'],
  ['current_pending', 'eod_pending', '等待今日收盘日线'],
  ['current_ready', 'ready', '今日日线已就绪'],
])('renders daily target mode %s', (mode, dailyStatus, label) => {
  render(
    <OperationsStatusCard
      runtime={runtime({
        daily_data_state: dailyStatus,
        daily_status: dailyStatus,
        artifact_freshness: 'current',
        artifact_status: 'current',
        daily_freshness_ready: mode !== 'current_pending',
        daily_target_mode: mode,
        daily_target_day: mode === 'previous_completed' ? '2026-04-29' : '2026-04-30',
        pending_eod_day: mode === 'current_pending' ? '2026-04-30' : null,
        eod_probe: mode === 'current_pending' ? { ready: false, ok_count: 1, next_retry_after: '2026-04-30T15:10:00Z' } : null,
      })}
    />,
  )

  expect(screen.getAllByText(label)).toHaveLength(1)
})

it('does not show current-ready text when full daily freshness is blocked', () => {
  render(
    <OperationsStatusCard
      runtime={runtime({
        daily_data_state: 'freshness_blocked',
        daily_status: 'freshness_blocked',
        artifact_freshness: 'blocked',
        artifact_status: 'blocked',
        daily_freshness_ready: false,
        daily_target_mode: 'current_ready',
        daily_target_day: '2026-05-13',
        daily_checked_count: 50,
        daily_stale_count: 1,
        daily_stale_symbols: ['002594'],
        daily_blocking_reason: '日线数据未补齐到 2026-05-13，当前不发布正式推荐',
      })}
    />,
  )

  expect(screen.getAllByText('日线未就绪').length).toBeGreaterThan(0)
  expect(screen.queryByText('今日日线已就绪')).not.toBeInTheDocument()
  expect(screen.getByText('日线数据未补齐到 2026-05-13，当前不发布正式推荐')).toBeInTheDocument()
  expect(screen.getByText('50 / 1')).toBeInTheDocument()
})

it('shows operation feedback after a tool run', () => {
  const result: OpsRunResponse = {
    operation: 'gp-rebuild-daybook',
    status: 'ok',
    message: '已刷新日线计划。',
    executed_at: '2026-01-01T15:02:00',
    result: {
      trade_day: '20260101',
      slot_status: 'OK',
      artifact_id: 'daily_1',
    },
    runtime: runtime(),
  }

  render(<OperationsStatusCard runtime={runtime()} opsResult={result} />)

  expect(screen.getByText('已刷新日线计划。')).toBeInTheDocument()
  expect(screen.getByText(/artifact daily_1/)).toBeInTheDocument()
})

it('shows publish lag and recommends postclose archive when daily data is ready but artifact is stale', () => {
  const { container } = render(
    <OperationsStatusCard
      runtime={runtime({
        book_freshness: 'lagging',
        daily_data_state: 'ready',
        daily_status: 'ready',
        daily_freshness_ready: true,
        daily_target_mode: 'current_ready',
        daily_stale_count: 0,
        artifact_freshness: 'lagging',
        artifact_status: 'lagging',
        artifact_lag_reason: 'daily_ready_current_artifact_meta_mismatch:market_phase',
        artifact_lag_fields: ['market_phase'],
      })}
    />,
  )

  expect(screen.getAllByText('日线已就绪，发布待归档').length).toBeGreaterThan(0)
  expect(screen.getByText('daily_ready_current_artifact_meta_mismatch:market_phase')).toBeInTheDocument()
  expect(container.querySelector('button[data-service="gp-postclose-archive"]')).toHaveClass('ant-btn-primary')
})

it('does not recommend manual archive when postclose daily artifact is current', () => {
  const { container } = render(
    <OperationsStatusCard
      runtime={runtime({
        book_freshness: 'postclose_ready',
        daily_data_state: 'ready',
        daily_status: 'ready',
        daily_freshness_ready: true,
        daily_target_mode: 'current_ready',
        daily_stale_count: 0,
        artifact_stage: 'daily_plan',
        artifact_freshness: 'current',
        artifact_status: 'current',
      })}
    />,
  )

  expect(screen.getAllByText('今日日线已就绪').length).toBeGreaterThan(0)
  expect(container.querySelector('button[data-service="gp-postclose-archive"]')).not.toHaveClass('ant-btn-primary')
})

it('shows the lunch data update state without using the trading recommendation state', () => {
  render(
    <OperationsStatusCard
      runtime={runtime({
        market_phase: 'LUNCH_BREAK',
        intraday_runtime_enabled: true,
        pulse_trade_day: '20260717',
        pulse_target_trade_day: '20260717',
        pulse_slot_at: '2026-07-17 11:30:00',
        pulse_target_slot_at: '2026-07-17 11:30:00',
        slot_status: 'OK',
        artifact_freshness: 'current',
        publish_allowed: false,
        tradeability_state: 'blocked',
      })}
      lunch={{
        schema_version: 'lunch_snapshot.v1',
        kind: 'lunch_snapshot',
        trade_day: '20260717',
        market_phase: 'LUNCH_BREAK',
        state: 'READY',
        session: {
          name: 'morning_session',
          target_closed_at: '2026-07-17T11:30:00+08:00',
          completed_at: '2026-07-17T11:30:00+08:00',
          complete: true,
        },
        daily: { effective_day: '20260716', target_mode: 'previous_completed', today_complete: false },
        market: { gate_reasons: [] },
      }}
    />,
  )

  expect(screen.getByText('午盘数据已完成 · 11:30')).toBeInTheDocument()
  expect(screen.getByText('上午交易时段数据已收齐；今日收盘日线尚未完成。')).toBeInTheDocument()
})
