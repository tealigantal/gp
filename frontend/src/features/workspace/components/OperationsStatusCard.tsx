import { Alert, Button, Space, Tag, Typography } from 'antd'
import type { OpsRunResponse, RuntimeStatus, RuntimeToolInfo } from '../../../shared/contracts'
import { dailyTargetModeMeta, fmtDateTime, runtimeFreshnessMeta } from '../runtimeLabels'

interface OperationsStatusCardProps {
  runtime?: RuntimeStatus | null
  onRunTool?: (service: string) => Promise<void>
  onRefreshRuntime?: () => Promise<void>
  runningToolService?: string | null
  isRunningTool?: boolean
  opsResult?: OpsRunResponse | null
  opsError?: string | null
}

function toolActionLabel(service: string) {
  if (service === 'gp-rebuild-daybook') return '重建日线计划'
  if (service === 'gp-postclose-archive') return '执行收盘归档'
  return '立即执行'
}

function toolPurpose(service: string) {
  if (service === 'gp-rebuild-daybook') return '重做日线推荐底稿。'
  if (service === 'gp-postclose-archive') return '固化收盘后的最终状态。'
  return ''
}

function summarizeResult(result?: Record<string, unknown>) {
  if (!result) return ''
  const bits: string[] = []
  if (typeof result.trade_day === 'string' && result.trade_day) bits.push(`交易日 ${result.trade_day}`)
  if (typeof result.slot_status === 'string' && result.slot_status) bits.push(`状态 ${result.slot_status}`)
  if (typeof result.artifact_id === 'string' && result.artifact_id) bits.push(`artifact ${result.artifact_id}`)
  if (typeof result.noop === 'boolean' && result.noop) bits.push('本次没有新增产物')
  if (typeof result.reason === 'string' && result.reason) bits.push(result.reason)
  return bits.join(' / ')
}

function recommendedTools(runtime?: RuntimeStatus | null, manualTools: RuntimeToolInfo[] = []) {
  const toolSet = new Set(manualTools.map((item) => item.service))
  const out: string[] = []
  const dailyStatus = String(runtime?.daily_status || '').toLowerCase()
  const eodPending = dailyStatus ? dailyStatus === 'eod_pending' : runtime?.daily_target_mode === 'current_pending'
  const previousCompleted = dailyStatus
    ? dailyStatus === 'previous_completed'
    : runtime?.daily_target_mode === 'previous_completed'
  const artifactLagging =
    dailyStatus === 'artifact_lagging' ||
    String(runtime?.book_freshness || '').toLowerCase() === 'lagging' || Boolean(runtime?.artifact_lag_reason)
  const dailyBlocked =
    dailyStatus === 'freshness_blocked' || (runtime?.daily_freshness_ready === false && !eodPending && !previousCompleted)
  if (artifactLagging && runtime?.market_phase === 'POSTCLOSE_PENDING' && toolSet.has('gp-postclose-archive')) {
    out.push('gp-postclose-archive')
  }
  if (artifactLagging && out.length === 0 && toolSet.has('gp-rebuild-daybook')) {
    out.push('gp-rebuild-daybook')
  }
  if (dailyBlocked && toolSet.has('gp-rebuild-daybook')) {
    out.push('gp-rebuild-daybook')
  }
  if (runtime?.market_phase === 'POSTCLOSE_PENDING' && !eodPending && toolSet.has('gp-postclose-archive')) {
    out.push('gp-postclose-archive')
  }
  return [...new Set(out)]
}

export function OperationsStatusCard({
  runtime,
  onRunTool,
  onRefreshRuntime,
  runningToolService,
  isRunningTool,
  opsResult,
  opsError,
}: OperationsStatusCardProps) {
  const freshness = runtimeFreshnessMeta(runtime)
  const dailyMode = dailyTargetModeMeta(runtime)
  const manualTools = (runtime?.services || []).filter((item) => item.mode !== 'always_on')
  const suggestedTools = recommendedTools(runtime, manualTools)
  const opSummary = summarizeResult(opsResult?.result)
  const dailyStatus = String(runtime?.daily_status || '').toLowerCase()
  const eodPending = dailyStatus ? dailyStatus === 'eod_pending' : runtime?.daily_target_mode === 'current_pending'
  const previousCompleted = dailyStatus
    ? dailyStatus === 'previous_completed'
    : runtime?.daily_target_mode === 'previous_completed'
  const dailyBlocked =
    dailyStatus === 'freshness_blocked' || (runtime?.daily_freshness_ready === false && !eodPending && !previousCompleted)
  const artifactLagging =
    dailyStatus === 'artifact_lagging' ||
    String(runtime?.book_freshness || '').toLowerCase() === 'lagging' || Boolean(runtime?.artifact_lag_reason)
  const dailyStatusLabel = freshness.label

  return (
    <section className="snapshot-section ops-card" aria-label="运行态与修复工具">
      <div className="snapshot-section-title">
        <Typography.Text strong>运行态与修复工具</Typography.Text>
      </div>

      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <div className="ops-status-strip">
          <Tag color="green">{runtime?.auto_update_service || 'gp-worker'}</Tag>
          <Tag>日线模式</Tag>
          {runtime?.data_provider ? <Tag>数据源 {runtime.data_provider}</Tag> : null}
          {dailyMode && dailyMode.label !== dailyStatusLabel ? <Tag color={dailyMode.color}>{dailyMode.label}</Tag> : null}
          <Tag color={artifactLagging ? 'volcano' : eodPending ? 'gold' : dailyBlocked ? 'volcano' : 'green'}>
            {dailyStatusLabel}
          </Tag>
        </div>

        <Typography.Paragraph type="secondary" className="ops-note">
          {artifactLagging
            ? runtime?.artifact_lag_reason || freshness.note
            : dailyBlocked
              ? runtime?.daily_blocking_reason || freshness.note
              : freshness.note}
        </Typography.Paragraph>

        <div className="ops-compact-grid">
          <div>
            <span>book 更新时间</span>
            <strong>{fmtDateTime(runtime?.book_updated_at)}</strong>
          </div>
          <div>
            <span>日线目标</span>
            <strong>{runtime?.daily_target_day || '--'}</strong>
          </div>
          <div>
            <span>检查 / 过期</span>
            <strong>
              {runtime?.daily_checked_count ?? 0} / {runtime?.daily_stale_count ?? 0}
            </strong>
          </div>
          {eodPending ? (
            <>
              <div>
                <span>等待日线</span>
                <strong>{runtime?.pending_eod_day || '--'}</strong>
              </div>
              <div>
                <span>EOD 探测</span>
                <strong>{runtime?.eod_probe?.ok_count ?? 0} / 3</strong>
              </div>
              <div>
                <span>下次自愈</span>
                <strong>{fmtDateTime(runtime?.eod_probe?.next_retry_after)}</strong>
              </div>
            </>
          ) : null}
        </div>

        <Space wrap className="ops-action-bar">
          <Button onClick={() => void onRefreshRuntime?.()}>刷新状态</Button>
          {manualTools.map((item) => (
            <Button
              key={item.service}
              data-service={item.service}
              type={
                suggestedTools.includes(item.service) || (item.service === 'gp-rebuild-daybook' && dailyBlocked)
                  ? 'primary'
                  : 'default'
              }
              loading={isRunningTool && runningToolService === item.service}
              disabled={Boolean(isRunningTool && runningToolService !== item.service)}
              onClick={() => void onRunTool?.(item.service)}
              title={toolPurpose(item.service) || item.description}
            >
              {toolActionLabel(item.service)}
            </Button>
          ))}
        </Space>

        {manualTools.length > 0 ? (
          <div className="ops-tool-tags">
            {manualTools.map((item) => (
              <Tag key={item.service}>{item.service}</Tag>
            ))}
          </div>
        ) : null}

        {runtime?.daily_failed_symbols?.length ? (
          <Typography.Text type="secondary" className="ops-note">
            刷新失败：{runtime.daily_failed_symbols.slice(0, 6).join('、')}
          </Typography.Text>
        ) : null}

        {opsError ? <Alert type="error" showIcon message="手工工具执行失败" description={opsError} /> : null}

        {opsResult ? (
          <Alert
            type={opsResult.status === 'ok' ? 'success' : 'warning'}
            showIcon
            message={opsResult.message}
            description={opSummary || '执行完成，页面状态已自动刷新。'}
          />
        ) : null}
      </Space>
    </section>
  )
}
