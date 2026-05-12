import { Space, Tag, Typography } from 'antd'
import type {
  CanonicalMessage,
  CanonicalRunArtifact,
  ChatResponse,
  HealthResponse,
  MarketBook,
  OpsRunResponse,
} from '../../../shared/contracts'
import { executionStateMeta, recommendationStateMeta, runActionLabel, slotStatusLabel } from '../presentation'
import { marketPhaseLabel } from '../runtimeLabels'
import { OperationsStatusCard } from './OperationsStatusCard'

interface DecisionSnapshotProps {
  book?: MarketBook
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

function dataQualityLabel(run: CanonicalRunArtifact | null) {
  const complete = run?.data_quality && typeof run.data_quality.complete === 'boolean' ? run.data_quality.complete : null
  if (complete === true) return '完整'
  if (complete === false) return '数据受限'
  return '--'
}

export function DecisionSnapshot({
  book,
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
  const marketPhase = marketPhaseLabel(run?.market_phase || book?.market_phase || health?.runtime?.market_phase)
  const slotState = slotStatusLabel(run?.slot_status || book?.slot_status || health?.runtime?.slot_status)
  const runRecommendation = recommendationStateMeta(run?.recommendation_state)
  const symbolRows = (run?.picks || []).length
    ? (run?.picks || []).slice(0, 5).map((pick) => ({
        key: pick.symbol,
        rank: pick.rank,
        symbol: pick.symbol,
        name: pick.name || '--',
        summary: pick.thesis || pick.why_selected || '暂无摘要',
        actionLabel: pick.action === 'BUY' ? '计划买入' : '暂不入场',
        recommendationState: pick.recommendation_state,
        executionState: pick.execution_state,
        championStrategy: pick.champion_strategy,
        entryText: pick.entry_text || '',
      }))
    : !run && book
      ? book.board.slice(0, 5).map((pick) => ({
          key: pick.symbol,
          rank: pick.rank,
          symbol: pick.symbol,
          name: pick.name || '--',
          summary: pick.pick?.thesis || pick.summary || '暂无摘要',
          actionLabel: pick.action === 'BUY' ? '计划买入' : '暂不入场',
          recommendationState: pick.recommendation_state,
          executionState: pick.execution_state,
          championStrategy: pick.champion_strategy,
          entryText: '',
        }))
      : []

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <section className="snapshot-section" aria-label="时效信息">
        <div className="snapshot-section-title">
          <Typography.Text strong>时效</Typography.Text>
          <Tag>{dataQualityLabel(run)}</Tag>
        </div>
        <div className="snapshot-fact-list">
          <div>
            <span>盘面时段</span>
            <strong>{marketPhase}</strong>
          </div>
          <div>
            <span>运行链路</span>
            <strong>日线计划</strong>
          </div>
          <div>
            <span>Daybook</span>
            <strong>{run?.daybook_effective_day || book?.daybook_effective_day || '--'}</strong>
          </div>
          <div>
            <span>状态</span>
            <strong>{slotState}</strong>
          </div>
        </div>
      </section>

      <OperationsStatusCard
        runtime={health?.runtime}
        onRunTool={onRunTool}
        onRefreshRuntime={onRefreshRuntime}
        runningToolService={runningToolService}
        isRunningTool={isRunningTool}
        opsResult={opsResult}
        opsError={opsError}
      />

      <section className="snapshot-section" aria-label="Top 标的">
        <div className="snapshot-section-title">
          <Typography.Text strong>Top 标的</Typography.Text>
          {run?.recommendation_state ? <Tag color={runRecommendation.color}>{runRecommendation.label}</Tag> : null}
          {run ? <Tag>{runActionLabel(run.run_action)}</Tag> : null}
        </div>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {symbolRows.length === 0 ? (
            <Typography.Text type="secondary" className="snapshot-empty-copy">
              当前没有同源 pick。可以直接在聊天里请求新的推荐，或者追问今天为什么暂不入场。
            </Typography.Text>
          ) : (
            symbolRows.map((row) => {
              const state = executionStateMeta(row.executionState)
              const recommendation = recommendationStateMeta(row.recommendationState)
              return (
                <div key={row.key} className="snapshot-symbol-row">
                  <div className="snapshot-symbol-rank">#{row.rank}</div>
                  <div className="snapshot-symbol-main">
                    <div className="snapshot-symbol-line">
                      <Typography.Text strong>{row.symbol}</Typography.Text>
                      <Typography.Text type="secondary">{row.name}</Typography.Text>
                    </div>
                    <Typography.Paragraph className="snapshot-symbol-note" type="secondary">
                      {row.summary}
                    </Typography.Paragraph>
                  </div>
                  <div className="snapshot-symbol-state">
                    {row.recommendationState ? <Tag color={recommendation.color}>{recommendation.label}</Tag> : <Tag>{row.actionLabel}</Tag>}
                    <Tag color={state.color}>{state.label}</Tag>
                    {row.championStrategy ? <Tag color="geekblue">{row.championStrategy}</Tag> : null}
                    {row.entryText ? <Typography.Text type="secondary">{row.entryText}</Typography.Text> : null}
                  </div>
                </div>
              )
            })
          )}
        </Space>
      </section>
    </Space>
  )
}
