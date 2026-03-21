import React from 'react'
import { Card, Tag, Typography, List } from 'antd'

export default function ExitDecisionCard(props: { symbol?: string; decision?: string; summary_reason?: string; primary_reasons?: string[]; trigger_conditions?: string[]; risk_notes?: string[]; onFocus?: (symbol: string) => void }) {
  const { symbol, decision, summary_reason, primary_reasons = [], trigger_conditions = [], risk_notes = [], onFocus } = props
  return (
    <Card size="small" title={<span>卖出判断 {symbol && <Tag onClick={() => symbol && onFocus?.(symbol)} style={{ cursor: 'pointer' }}>{symbol}</Tag>}</span>}>
      <Typography.Text>
        建议：{decision || 'HOLD'}
      </Typography.Text>
      {summary_reason && <div style={{ marginTop: 6 }}><Typography.Text type="secondary">{summary_reason}</Typography.Text></div>}
      {primary_reasons.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <Typography.Text strong>主要依据</Typography.Text>
          <List size="small" dataSource={primary_reasons.slice(0, 4)} renderItem={(t) => (<List.Item style={{ padding: '2px 0' }}>{t}</List.Item>)} />
        </div>
      )}
      {trigger_conditions.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <Typography.Text strong>触发条件</Typography.Text>
          <List size="small" dataSource={trigger_conditions.slice(0, 4)} renderItem={(t) => (<List.Item style={{ padding: '2px 0' }}>{t}</List.Item>)} />
        </div>
      )}
      {risk_notes.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <Typography.Text strong>风险提示</Typography.Text>
          <List size="small" dataSource={risk_notes.slice(0, 4)} renderItem={(t) => (<List.Item style={{ padding: '2px 0' }}>{t}</List.Item>)} />
        </div>
      )}
    </Card>
  )
}
