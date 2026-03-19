import React from 'react'
import { Card, List, Space, Tag, Typography } from 'antd'

export default function CompareCard(props: { symbols?: string[] | string; winner_symbol?: string; onFocus?: (symbol: string) => void }) {
  const { symbols: symin = [], winner_symbol, onFocus } = props
  const symbols = Array.isArray(symin) ? symin : (typeof symin === 'string' ? symin.split(',').map(s => s.trim()).filter(Boolean) : [])
  return (
    <Card size="small" title="对比">
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>
          参与对比：{symbols.map((s) => <Tag key={s} onClick={() => onFocus?.(s)} style={{ cursor: 'pointer' }}>{s}</Tag>)}
        </Typography.Text>
        {winner_symbol && (
          <Typography.Text>
            优胜：<Tag color="green">{winner_symbol}</Tag>
          </Typography.Text>
        )}
      </Space>
    </Card>
  )
}
