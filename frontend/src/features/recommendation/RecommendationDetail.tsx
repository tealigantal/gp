import { Card, Collapse, List, Space, Tag, Typography } from 'antd'
import type { RecommendationArtifact } from '../../api/contracts'

export default function RecommendationDetail({ artifact, onShowKline }: { artifact: RecommendationArtifact; onShowKline?: (symbol: string) => void }) {
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
                <div>reasons: {artifact.diagnostics.degrade_reasons.map((r: any) => r?.reason_code).filter(Boolean).join(', ')}</div>
              )}
            </div>
          )
        }]} />
      )}
    </Card>
  )
}

