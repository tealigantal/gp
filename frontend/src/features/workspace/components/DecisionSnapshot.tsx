import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type {
  CanonicalMessage,
  CanonicalRunArtifact,
  ChatResponse,
  HealthResponse,
  MarketBook,
  OpsRunResponse,
  SessionResponse,
} from '../../../shared/contracts'
import { fmtDateTime, marketPhaseLabel } from '../runtimeLabels'
import { OperationsStatusCard } from './OperationsStatusCard'

interface DecisionSnapshotProps {
  book?: MarketBook
  session?: SessionResponse
  latest?: ChatResponse | null
  health?: HealthResponse
  onRunTool?: (service: string) => Promise<void>
  onRefreshRuntime?: () => Promise<void>
  runningToolService?: string | null
  isRunningTool?: boolean
  opsResult?: OpsRunResponse | null
  opsError?: string | null
}

function resolveRun(latest?: ChatResponse | null): CanonicalRunArtifact | null {
  const message = latest?.message as CanonicalMessage | undefined
  if (message && 'run' in message && message.run) return message.run
  const snapshot = latest?.right_panel?.snapshot
  return snapshot && typeof snapshot === 'object' ? (snapshot as CanonicalRunArtifact) : null
}

function runTag(run: CanonicalRunArtifact | null, book?: MarketBook) {
  if (run?.run_action === 'NO_TRADE') return { text: '空仓 / 观察', color: 'default' as const }
  if (run?.non_trading) return { text: '下一交易窗口计划', color: 'blue' as const }
  if (run?.run_action === 'DEGRADED') return { text: '降级观察', color: 'gold' as const }
  if (run?.run_action === 'RECOMMEND') return { text: '执行计划', color: 'green' as const }
  if (book?.publish_allowed) return { text: '执行计划', color: 'green' as const }
  return { text: '观察中', color: 'default' as const }
}

function dataQualityLabel(run: CanonicalRunArtifact | null) {
  const complete = run?.data_quality && typeof run.data_quality.complete === 'boolean' ? run.data_quality.complete : null
  if (complete === true) return '完整'
  if (complete === false) return '降级'
  return '--'
}

export function DecisionSnapshot({
  book,
  session,
  latest,
  health,
  onRunTool,
  onRefreshRuntime,
  runningToolService,
  isRunningTool,
  opsResult,
  opsError,
}: DecisionSnapshotProps) {
  const run = resolveRun(latest)
  const tag = runTag(run, book)
  const picks = run?.picks || []
  const fallbackBoard = !run && book ? book.board.slice(0, 3) : []

  return (
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <div className="snapshot-summary">
        <Typography.Title level={4} style={{ margin: 0 }}>
          当前决策快照
        </Typography.Title>
        <Typography.Text className="section-subtitle">
          用一列信息看清当前 run、时效、手工恢复路径和关注标的。
        </Typography.Text>
      </div>

      <Card className="snapshot-card snapshot-overview-card" size="small">
        <Space size={[8, 8]} wrap>
          <Tag color={tag.color}>{tag.text}</Tag>
          <Tag>会话更新时间 {fmtDateTime(session?.session?.updated_at || session?.session?.created_at)}</Tag>
          <Tag>run {run?.run_id || latest?.run_id || '--'}</Tag>
          <Tag>artifact {run?.artifact_id || book?.artifact_id || book?.book_version || '--'}</Tag>
        </Space>
      </Card>

      <OperationsStatusCard
        runtime={health?.runtime}
        onRunTool={onRunTool}
        onRefreshRuntime={onRefreshRuntime}
        runningToolService={runningToolService}
        isRunningTool={isRunningTool}
        opsResult={opsResult}
        opsError={opsError}
      />

      <Card className="snapshot-card" size="small" title="时效信息">
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="盘面时段">{marketPhaseLabel(run?.market_phase || book?.market_phase)}</Descriptions.Item>
          <Descriptions.Item label="最新 5 分钟">{fmtDateTime(run?.pulse_slot_at || book?.last_closed_5m)}</Descriptions.Item>
          <Descriptions.Item label="Daybook 生效日">
            {run?.daybook_effective_day || book?.daybook_effective_day || '--'}
          </Descriptions.Item>
          <Descriptions.Item label="slot 状态">{run?.slot_status || book?.slot_status || '--'}</Descriptions.Item>
          <Descriptions.Item label="数据质量">{dataQualityLabel(run)}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card className="snapshot-card" size="small" title="Top Symbols">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {picks.length === 0 && fallbackBoard.length === 0 ? (
            <Typography.Text type="secondary">
              当前没有同源 pick。可以直接在聊天里请求新的推荐，或追问今天是否适合空仓观察。
            </Typography.Text>
          ) : (
            picks
              .map((pick) => (
                <div key={pick.symbol} className="snapshot-row">
                  <div>
                    <Typography.Text strong>
                      #{pick.rank} {pick.symbol} {pick.name || ''}
                    </Typography.Text>
                    <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                      {pick.thesis || pick.why_selected || '暂无摘要'}
                    </Typography.Paragraph>
                  </div>
                  <Space size={6} wrap>
                    <Tag>{pick.action}</Tag>
                    <Tag>{pick.execution_state}</Tag>
                    <Tag>{pick.entry_text || '待确认'}</Tag>
                  </Space>
                </div>
              ))
              .concat(
                fallbackBoard.map((pick) => (
                  <div key={pick.symbol} className="snapshot-row">
                    <div>
                      <Typography.Text strong>
                        #{pick.rank} {pick.symbol} {pick.name || ''}
                      </Typography.Text>
                      <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
                        {pick.pick?.thesis || pick.summary || '暂无摘要'}
                      </Typography.Paragraph>
                    </div>
                    <Space size={6} wrap>
                      <Tag>{pick.action || 'WATCH'}</Tag>
                      <Tag>{pick.execution_state}</Tag>
                    </Space>
                  </div>
                )),
              )
          )}
        </Space>
      </Card>

      {run?.status_reason ? (
        <Card className="snapshot-card" size="small" title="状态说明">
          <Typography.Paragraph style={{ marginBottom: 0 }}>{run.status_reason}</Typography.Paragraph>
        </Card>
      ) : null}
    </Space>
  )
}
