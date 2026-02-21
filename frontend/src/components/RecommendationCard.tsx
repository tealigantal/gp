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
  props: { picks: PickItem[]; onShowKline?: (symbol: string) => void }
) {
  const { picks, onShowKline } = props
  const data = Array.isArray(picks) ? picks.slice(0, 6) : []
  return (
    <Card
      size="small"
      title={(
        <Space>
          <span>推荐清单</span>
          <Tag color="blue">{data.length}</Tag>
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
                {it.theme && <Tag color="geekblue">{it.theme}</Tag>}
              </Space>
              {it.champion?.strategy && (
                <Typography.Text type="secondary">
                  策略: {String(it.champion.strategy)}
                  {it.champion.score ? ` · 分数 ${it.champion.score}` : ''}
                </Typography.Text>
              )}
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

