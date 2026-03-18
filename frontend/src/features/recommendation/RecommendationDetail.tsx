import { Card, Collapse, List, Space, Tag, Typography } from 'antd'
import type { RecommendationArtifact } from '../../api/contracts'

export default function RecommendationDetail({ artifact, onShowKline, onAsk }: { artifact: RecommendationArtifact; onShowKline?: (symbol: string) => void; onAsk?: (text: string) => void }) {
  // V2 decision-chain preferred view
  if (artifact.artifact_version === 'v2' && artifact.v2) {
    const art = artifact.v2
    const items = Array.isArray(art.items) ? art.items : []
    const tradeable = !!art.tradeable
    const runGate = art.run_gating as any
    return (
      <Card size="small" title={(
        <Space>
          <span>推荐清单</span>
          <Tag color="blue">{items.length}</Tag>
          {tradeable ? <Tag color="green">TRADEABLE</Tag> : <Tag color="red">NO-TRADE</Tag>}
          {art.market_regime && <Tag>{String(art.market_regime)}</Tag>}
        </Space>
      )}>
        {/* rationale summary */}
        {typeof (art as any).selection_rationale === 'string' && (
          <div style={{ marginBottom: 4, color: 'rgba(0,0,0,0.65)' }}>入选摘要: {(art as any).selection_rationale}</div>
        )}
        {typeof (art as any).rejection_summary === 'string' && (
          <div style={{ marginBottom: 4, color: 'rgba(0,0,0,0.65)' }}>淘汰摘要: {(art as any).rejection_summary}</div>
        )}
        <div style={{ marginBottom: 8, color: 'rgba(0,0,0,0.65)' }}>
          <div>as_of: {art.as_of || '-'}</div>
          {!!runGate && (
            <div>run_gating: {String(runGate.decision)}{Array.isArray(runGate.reasons) && runGate.reasons.length ? ` (${runGate.reasons.join(', ')})` : ''}</div>
          )}
          {!tradeable && art.reason && (
            <div>reason: {art.reason}</div>
          )}
          {Array.isArray(art.themes) && art.themes.length > 0 && (
            <div>themes: {art.themes.map((t) => <Tag key={String(t)}>{String(t)}</Tag>)}</div>
          )}
        </div>
        {/* quick follow-up actions */}
        {onAsk && (
          <div style={{ marginBottom: 8 }}>
            <Space size={8} wrap>
              <a onClick={() => onAsk('为什么第一只排第一')}>为什么是第一只</a>
              {items.length >= 2 && <a onClick={() => onAsk('第二只为什么不是第一只')}>第二只为什么不是第一只</a>}
              {!tradeable && items.length === 0 ? null : <a onClick={() => onAsk('对比前两只')}>对比前两只</a>}
              {!tradeable && <a onClick={() => onAsk('为什么空仓')}>为什么空仓</a>}
              <a onClick={() => onAsk('重新算')}>重新算</a>
            </Space>
          </div>
        )}
        <List
          dataSource={items}
          renderItem={(it) => (
            <List.Item key={String((it as any).symbol)} actions={[
              <a key="k" onClick={() => onShowKline?.(String((it as any).symbol))}>查看K线</a>
            ]}>
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                  <Typography.Text strong>
                    {String((it as any).symbol)}{(it as any).name ? ` · ${(it as any).name}` : ''}
                  </Typography.Text>
                  {(it as any).strategy && <Tag color="geekblue">{String((it as any).strategy)}</Tag>}
                  {(it as any).gating_decision?.decision && <Tag color={(it as any).gating_decision.decision === 'allow' ? 'green' : ((it as any).gating_decision.decision === 'degraded' ? 'orange' : 'red')}>{String((it as any).gating_decision.decision).toUpperCase()}</Tag>}
                  <Tag color={(it as any).actionable ? 'green' : 'default'}>{(it as any).actionable ? 'BUY' : 'WATCH'}</Tag>
                </Space>
                {(it as any).thesis && (<Typography.Text type="secondary">{String((it as any).thesis)}</Typography.Text>)}
                <div style={{ color: 'rgba(0,0,0,0.65)' }}>
                  {Array.isArray((it as any).entry_zone) && <div>入场区间：{String((it as any).entry_zone[0])} ~ {String((it as any).entry_zone[1])}</div>}
                  {(it as any).stop != null && <div>止损：{String((it as any).stop)}</div>}
                  {Array.isArray((it as any).take_profit) && (it as any).take_profit.length > 0 && <div>止盈：{(it as any).take_profit.join(' / ')}</div>}
                  {(it as any).reward_risk != null && <div>RR：{String((it as any).reward_risk)}</div>}
                  {(it as any).execution_state && <div>状态：{String((it as any).execution_state)}{(it as any).actionable ? ' · 可执行' : ''}</div>}
                  {((it as any).final_score != null || (it as any).confidence != null || (it as any).reliability_score != null) && (
                    <div>scores: final={String((it as any).final_score ?? '-')} / conf={String((it as any).confidence ?? '-')} / rel={String((it as any).reliability_score ?? '-')}</div>
                  )}
                  {Array.isArray((it as any).risk_flags) && (it as any).risk_flags.length > 0 && <div>风险：{(it as any).risk_flags.join(', ')}</div>}
                  {Array.isArray((it as any).invalidation) && (it as any).invalidation.length > 0 && <div>失效条件：{(it as any).invalidation.join(', ')}</div>}
                  {Array.isArray((it as any).gating_decision?.reasons) && (it as any).gating_decision.reasons.length > 0 && <div>门控：{(it as any).gating_decision.reasons.join(', ')}</div>}
                </div>
              </Space>
            </List.Item>
          )}
        />
      </Card>
    )
  }
  // Legacy fallback view (v1-style)
  const picks = artifact.picks || []
  return (
    <Card size="small" title={(
      <Space>
        <span>推荐清单</span>
        <Tag color="blue">{picks.length}</Tag>
        {artifact.tradeable === true && <Tag color="green">TRADEABLE</Tag>}
      </Space>
    )}>
      <List
        dataSource={picks}
        renderItem={(it) => (
          <List.Item key={it.symbol} actions={[
            <a key="k" onClick={() => onShowKline?.(it.symbol)}>查看K线</a>
          ]}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>{it.symbol}{it.name ? ` · ${it.name}` : ''}</Typography.Text>
                {it.theme && <Tag color="geekblue">{it.theme}</Tag>}
              </Space>
              {it.champion?.strategy && (
                <Typography.Text type="secondary">
                  策略: {String(it.champion.strategy)}{typeof it.champion.score === 'number' ? ` · 分数 ${it.champion.score}` : ''}
                </Typography.Text>
              )}
              {it.trade_plan && (() => {
                const tp = it.trade_plan
                const b = tp.bands || {}
                const fmt = (v?: number) => (v == null || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(2))
                const hasBands = b.S1 != null || b.R1 != null
                return (
                  <div style={{ color: 'rgba(0,0,0,0.65)' }}>
                    {hasBands && <div>关键带：S1 {fmt(b.S1)} ｜ S2 {fmt(b.S2)} ｜ R1 {fmt(b.R1)} ｜ R2 {fmt(b.R2)}</div>}
                    {tp.entry && <div>买点: {Array.isArray(tp.entry) ? tp.entry.join(' / ') : tp.entry}</div>}
                    {tp.stop && <div>止损: {tp.stop}</div>}
                    {tp.take && <div>止盈: {Array.isArray(tp.take) ? tp.take.join(' / ') : tp.take}</div>}
                    {tp.risk && <div>风控：止损 {tp.risk.stop_loss || '-'} ｜ 时间止损 {tp.risk.time_stop || '-'} ｜ 禁止摊平 {String(tp.risk.no_averaging_down ?? '-')}</div>}
                  </div>
                )
              })()}
            </Space>
          </List.Item>
        )}
      />
      {/* Debug / diagnostics in collapsed area */}
      {artifact.diagnostics && (
        <Collapse style={{ marginTop: 8 }} items={[{
          key: 'debug', label: '调试信息（默认折叠）', children: (
            <div>
              <div>degraded: {String(artifact.diagnostics.degraded)}</div>
              {Array.isArray(artifact.diagnostics.degrade_reasons) && artifact.diagnostics.degrade_reasons.length > 0 && (
                <div>reasons: {artifact.diagnostics.degrade_reasons.map((r) => (r && typeof r === 'object' && 'reason_code' in (r as { reason_code?: unknown }) ? String((r as { reason_code?: unknown }).reason_code) : 'UNKNOWN')).filter(Boolean).join(', ')}</div>
              )}
            </div>
          )
        }]} />
      )}
    </Card>
  )
}
