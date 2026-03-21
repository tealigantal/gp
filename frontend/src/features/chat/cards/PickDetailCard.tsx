import React from 'react'
import { Card, Descriptions, Tag, Typography } from 'antd'

export default function PickDetailCard(props: { symbol?: string; item?: any; onFocus?: (symbol: string) => void }) {
  const { symbol, item, onFocus } = props
  const st = typeof item === 'object' && item ? item : {}
  return (
    <Card size="small" title={<span>标的研究 {symbol && <Tag onClick={() => symbol && onFocus?.(symbol)} style={{ cursor: 'pointer' }}>{symbol}</Tag>}</span>}>
      <Descriptions size="small" column={1} bordered>
        {st.thesis && (
          <Descriptions.Item label="观点">
            <Typography.Text>{String(st.thesis)}</Typography.Text>
          </Descriptions.Item>
        )}
        {Array.isArray(st.entry_zone) && st.entry_zone.length >= 2 && (
          <Descriptions.Item label="买点">{`${st.entry_zone[0]} ~ ${st.entry_zone[1]}`}</Descriptions.Item>
        )}
        {st.stop != null && <Descriptions.Item label="止损">{String(st.stop)}</Descriptions.Item>}
        {Array.isArray(st.take_profit) && st.take_profit.length > 0 && (
          <Descriptions.Item label="止盈">{st.take_profit.map((v: any) => String(v)).join(', ')}</Descriptions.Item>
        )}
        {st.execution_state && (
          <Descriptions.Item label="执行状态">
            <Typography.Text>{String(st.execution_state)}{st.actionable ? '（可执行）' : ''}</Typography.Text>
          </Descriptions.Item>
        )}
      </Descriptions>
    </Card>
  )
}
