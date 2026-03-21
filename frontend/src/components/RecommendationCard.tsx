import React from 'react'
import { Card, List, Space, Tag, Typography } from 'antd'
import type { RecommendationArtifact } from '../api/contracts'

export default function RecommendationCard({ artifact, onShowKline }: { artifact: RecommendationArtifact; onShowKline?: (symbol: string) => void }) {
  const picks = Array.isArray(artifact.picks) ? artifact.picks.slice(0, 6) : []
  const fmt = (v?: number) => (v == null || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(2))
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
          <List.Item key={it.symbol} actions={[<a key="k" onClick={() => onShowKline?.(it.symbol)}>查看K线</a>] }>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>{it.symbol}{it.name ? ` · ${it.name}` : ''}</Typography.Text>
                {it.theme && <Tag color="geekblue">{it.theme}</Tag>}
              </Space>
              {it.champion?.strategy && (
                <Typography.Text type="secondary">策略: {String(it.champion.strategy)}{typeof it.champion.score === 'number' ? ` · 分数 ${it.champion.score}` : ''}</Typography.Text>
              )}
              {it.trade_plan && (() => {
                const b = it.trade_plan.bands || {}
                const hasBands = b.S1 != null || b.R1 != null
                return (
                  <div style={{ color: 'rgba(0,0,0,0.65)' }}>
                    {hasBands && <div>关键带：S1 {fmt(b.S1)} ｜ S2 {fmt(b.S2)} ｜ R1 {fmt(b.R1)} ｜ R2 {fmt(b.R2)}</div>}
                    {it.trade_plan.entry && <div>买点: {Array.isArray(it.trade_plan.entry) ? it.trade_plan.entry.join(' / ') : it.trade_plan.entry}</div>}
                    {it.trade_plan.stop && <div>止损: {it.trade_plan.stop}</div>}
                    {it.trade_plan.take && <div>止盈: {Array.isArray(it.trade_plan.take) ? it.trade_plan.take.join(' / ') : it.trade_plan.take}</div>}
                    {it.trade_plan.risk && <div>风控：止损 {it.trade_plan.risk.stop_loss || '-'} ｜ 时间止损 {it.trade_plan.risk.time_stop || '-'} ｜ 禁止摊平 {String(it.trade_plan.risk.no_averaging_down ?? '-')}</div>}
                  </div>
                )
              })()}
            </Space>
          </List.Item>
        )}
      />
    </Card>
  )
}
