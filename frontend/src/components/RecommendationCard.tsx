import React from 'react'
import { Card, List, Space, Button, Tag, Typography } from 'antd'

type PickItem = {
  symbol: string
  name?: string
  theme?: string
  champion?: { strategy?: string; score?: number }
  trade_plan?: { entry?: string | string[]; stop?: string; take?: string | string[] }
  [k: string]: any
}

export default function RecommendationCard(
  props: { picks: PickItem[]; meta?: any; onShowKline?: (symbol: string) => void }
) {
  const { picks, meta, onShowKline } = props
  const data = Array.isArray(picks) ? picks.slice(0, 6) : []
  return (
    <Card
      size="small"
      title={(
        <Space>
          <span>推荐清单</span>
          <Tag color="blue">{data.length}</Tag>
          {(() => {
            try {
              const tradeable = (meta && typeof meta === 'object') ? meta.tradeable : undefined
              const degraded = (meta && typeof meta === 'object') ? (meta.debug?.degraded === true) : undefined
              if (degraded || tradeable === false) return <Tag color="red">DEGRADED</Tag>
              if (tradeable === true) return <Tag color="green">TRADEABLE</Tag>
            } catch {}
            return null
          })()}
        </Space>
      )}
      style={{ margin: '8px 0' }}
    >
      <List
        dataSource={data}
        renderItem={(it) => (
          <List.Item
            key={it.symbol}
            actions={[
              <Button key="k" size="small" type="link" onClick={() => onShowKline?.(it.symbol)}>
                查看K线
              </Button>,
            ]}
          >
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>
                  {it.symbol}
                  {it.name ? ` · ${it.name}` : ''}
                </Typography.Text>
                {(() => {
                  const th = (it as any).theme
                  const show = th && typeof th === 'string' && !th.startsWith('概念-')
                  return show ? <Tag color="geekblue">{th}</Tag> : null
                })()}
              </Space>
              {it.champion?.strategy && (
                <Typography.Text type="secondary">
                  策略: {String(it.champion.strategy)}
                  {it.champion.score ? ` · 分数 ${it.champion.score}` : ''}
                </Typography.Text>
              )}
              {it.trade_plan && (() => {
                const tp: any = it.trade_plan || {}
                const bands = tp.bands || {}
                const actions = tp.actions || {}
                const diag = tp.diagnostics || {}
                const fmt = (v: any) => (v == null || Number.isNaN(Number(v)) ? '-' : Number(v).toFixed(2))
                const hasBands = bands && (bands.S1 != null || bands.R1 != null)
                if (!hasBands) return null
                return (
                  <div style={{ color: 'rgba(0,0,0,0.65)' }}>
                    <div>关键带：S1 {fmt(bands.S1)} ｜ S2 {fmt(bands.S2)} ｜ R1 {fmt(bands.R1)} ｜ R2 {fmt(bands.R2)}</div>
                    <div>A窗：{actions.window_A || '—'} ｜ B窗：{actions.window_B || '—'}</div>
                    {tp.risk && (
                      <div>风控：止损 {tp.risk.stop_loss || '-'} ｜ 时间止损 {tp.risk.time_stop || '-'} ｜ 禁止摊平 {String(tp.risk.no_averaging_down ?? '-')}</div>
                    )}
                    {diag && (diag.setup_age != null) && (
                      <div>诊断：age {diag.setup_age} ｜ stale {String(diag.stale)}{diag.sanity_warning ? ` ｜ ${diag.sanity_warning}` : ''}{diag.fallback_reason ? ` ｜ ${diag.fallback_reason}` : ''}{diag.band_source ? ` ｜ ${diag.band_source}` : ''}</div>
                    )}
                  </div>
                )
              })()}
              {it.trade_plan && (
                <Typography.Text type="secondary">
                  买点: {Array.isArray(it.trade_plan.entry) ? it.trade_plan.entry.join(' / ') : (it.trade_plan.entry || '-')}
                  ，止损: {it.trade_plan.stop || '-'}
                  ，止盈: {Array.isArray(it.trade_plan.take) ? it.trade_plan.take.join(' / ') : (it.trade_plan.take || '-')}
                </Typography.Text>
              )}
            </Space>
          </List.Item>
        )}
      />
    </Card>
  )
}
