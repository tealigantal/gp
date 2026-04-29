import { Alert, Button, Card, Descriptions, List, Space, Tag, Typography } from 'antd'
import type { OpsRunResponse, RuntimeStatus, RuntimeToolInfo } from '../../../shared/contracts'
import { fmtDateTime, marketPhaseLabel, runtimeFreshnessMeta } from '../runtimeLabels'

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
  if (service === 'gp-rebuild-daybook') return '重建日计划'
  if (service === 'gp-replay-today') return '回放今日 5 分钟'
  if (service === 'gp-postclose-archive') return '执行收盘归档'
  return '立即执行'
}

function toolPurpose(service: string) {
  if (service === 'gp-rebuild-daybook') return '重做日级推荐底稿，不修 5 分钟。'
  if (service === 'gp-replay-today') return '补齐盘中执行态，不修日线。'
  if (service === 'gp-postclose-archive') return '固化收盘后状态。'
  return ''
}

function summarizeResult(result?: Record<string, unknown>) {
  if (!result) return ''
  const current = result.current
  const bits: string[] = []

  if (typeof result.trade_day === 'string' && result.trade_day) bits.push(`交易日 ${result.trade_day}`)
  if (typeof result.replayed_slots === 'number') bits.push(`已回放 ${result.replayed_slots} 个 slot`)
  if (typeof result.slot_status === 'string' && result.slot_status) bits.push(`slot 状态 ${result.slot_status}`)
  if (typeof result.artifact_id === 'string' && result.artifact_id) bits.push(`artifact ${result.artifact_id}`)
  if (typeof result.noop === 'boolean' && result.noop) bits.push('这次没有新增产物')
  if (current && typeof current === 'object') {
    const currentRecord = current as Record<string, unknown>
    if (typeof currentRecord.slot_status === 'string' && currentRecord.slot_status) bits.push(`当前 slot ${currentRecord.slot_status}`)
    if (typeof currentRecord.slot_at === 'string' && currentRecord.slot_at) bits.push(`定位到 ${currentRecord.slot_at}`)
  }
  return bits.join(' · ')
}

function recommendedTools(runtime?: RuntimeStatus | null, manualTools: RuntimeToolInfo[] = []) {
  const toolSet = new Set(manualTools.map((item) => item.service))
  const out: string[] = []
  if (runtime?.daily_freshness_ready === false && toolSet.has('gp-rebuild-daybook')) out.push('gp-rebuild-daybook')
  if (
    runtime?.intraday_runtime_enabled !== false &&
    (runtime?.slot_status || '').toUpperCase() !== 'OK' &&
    toolSet.has('gp-replay-today')
  ) {
    out.push('gp-replay-today')
  }
  if (runtime?.market_phase === 'POSTCLOSE_PENDING' && toolSet.has('gp-postclose-archive')) out.push('gp-postclose-archive')
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
  const manualTools = (runtime?.services || []).filter((item) => item.mode !== 'always_on')
  const suggestedTools = recommendedTools(runtime, manualTools)
  const opSummary = summarizeResult(opsResult?.result)
  const dailyBlocked = runtime?.daily_freshness_ready === false

  return (
    <Card className="snapshot-card ops-card" size="small" title="运行与工具">
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        <Card size="small" className="ops-subcard" title="自动更新状态">
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space wrap>
              <Tag color="green">{runtime?.auto_update_service || 'gp-worker'}</Tag>
              <Tag color={freshness.color}>{freshness.label}</Tag>
              {runtime?.intraday_runtime_enabled === false ? <Tag>日级模式</Tag> : null}
              {runtime?.data_provider ? <Tag>数据源 {runtime.data_provider}</Tag> : null}
              {runtime?.worker_poll_interval_sec ? <Tag>{runtime.worker_poll_interval_sec}s 轮询</Tag> : null}
            </Space>
            <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
              {freshness.note}
            </Typography.Paragraph>
          </Space>
        </Card>

        <Card size="small" className="ops-subcard" title="日线 Freshness">
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space wrap>
              <Tag color={dailyBlocked ? 'volcano' : 'green'}>{dailyBlocked ? '日线未就绪' : '日线已补齐'}</Tag>
              <Tag>目标交易日 {runtime?.daily_target_day || '--'}</Tag>
              <Tag>检查 {runtime?.daily_checked_count ?? 0}</Tag>
              <Tag>过期 {runtime?.daily_stale_count ?? 0}</Tag>
            </Space>
            <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
              {runtime?.daily_blocking_reason || '当前决策链相关 symbol 会在推荐前做严格日线 freshness 校验。'}
            </Typography.Paragraph>
            {runtime?.daily_last_reconcile_at ? (
              <Typography.Text type="secondary">最近校准：{fmtDateTime(runtime.daily_last_reconcile_at)}</Typography.Text>
            ) : null}
            {runtime?.daily_failed_symbols?.length ? (
              <Typography.Text type="secondary">刷新失败：{runtime.daily_failed_symbols.slice(0, 6).join('、')}</Typography.Text>
            ) : null}
          </Space>
        </Card>

        <Card size="small" className="ops-subcard" title="手工恢复工具">
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <Space wrap className="ops-action-bar">
              <Button onClick={() => void onRefreshRuntime?.()}>刷新状态</Button>
              {suggestedTools.map((service) => (
                <Button
                  key={service}
                  type={service === 'gp-rebuild-daybook' ? 'primary' : 'default'}
                  loading={isRunningTool && runningToolService === service}
                  disabled={Boolean(isRunningTool && runningToolService !== service)}
                  onClick={() => void onRunTool?.(service)}
                >
                  {toolActionLabel(service)}
                </Button>
              ))}
            </Space>

            {manualTools.length > 0 ? (
              <List
                className="ops-tool-list"
                size="small"
                dataSource={manualTools}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Button
                        key={`${item.service}-run`}
                        size="small"
                        type={item.service === 'gp-rebuild-daybook' && dailyBlocked ? 'primary' : 'default'}
                        loading={isRunningTool && runningToolService === item.service}
                        disabled={Boolean(isRunningTool && runningToolService !== item.service)}
                        onClick={() => void onRunTool?.(item.service)}
                      >
                        {toolActionLabel(item.service)}
                      </Button>,
                    ]}
                  >
                    <div className="ops-tool-row">
                      <Space wrap>
                        <Tag>{item.service}</Tag>
                        {item.profile ? <Tag color="blue">{item.profile}</Tag> : null}
                      </Space>
                      <Typography.Paragraph style={{ margin: '6px 0 0' }}>
                        {toolPurpose(item.service) || item.description}
                      </Typography.Paragraph>
                      <Typography.Text type="secondary" className="tool-service-note">
                        {item.command}
                      </Typography.Text>
                    </div>
                  </List.Item>
                )}
              />
            ) : null}
          </Space>
        </Card>

        {opsError ? <Alert type="error" showIcon message="手工工具执行失败" description={opsError} /> : null}

        {opsResult ? (
          <Alert
            type={opsResult.status === 'ok' ? 'success' : 'warning'}
            showIcon
            message={opsResult.message}
            description={opSummary || '执行完成，页面状态已自动刷新。'}
          />
        ) : null}

        <Descriptions size="small" column={1}>
          <Descriptions.Item label="当前时段">{marketPhaseLabel(runtime?.market_phase)}</Descriptions.Item>
          <Descriptions.Item label="book 更新时间">{fmtDateTime(runtime?.book_updated_at)}</Descriptions.Item>
          <Descriptions.Item label="最新 5 分钟">{fmtDateTime(runtime?.last_closed_5m)}</Descriptions.Item>
          <Descriptions.Item label="目标 slot">{runtime?.pulse_slot_at || '--'}</Descriptions.Item>
          <Descriptions.Item label="slot 状态">{runtime?.slot_status || '--'}</Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
