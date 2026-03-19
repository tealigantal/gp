import React from 'react'
import { Card, Tag, Typography } from 'antd'

export default function NoTradeCard(props: { decision?: string; reason?: string }) {
  const { decision, reason } = props
  return (
    <Card size="small" title={<span>空仓原因 {decision && <Tag color="red">{decision}</Tag>}</span>}>
      <Typography.Paragraph style={{ marginBottom: 0 }}>{reason || '本轮不可交易，详见右侧状态。'}</Typography.Paragraph>
    </Card>
  )
}

