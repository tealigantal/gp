import { Card, List, Space, Tag, Typography } from 'antd'
import type { CompareArtifact } from '../../../shared/contracts'
import { executionStateMeta, riskLabel } from '../presentation'

interface CompareMessageCardProps {
  compare: CompareArtifact
  text: string
}

export function CompareMessageCard({ compare, text }: CompareMessageCardProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="geekblue">对比结论</Tag>
          {compare.leader_symbol ? <Tag>当前优先 {compare.leader_symbol}</Tag> : null}
        </Space>

        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>

        {compare.comparison_points.length > 0 ? (
          <List size="small" dataSource={compare.comparison_points} renderItem={(item) => <List.Item>{item}</List.Item>} />
        ) : null}

        {compare.ranking.length > 0 ? (
          <List
            size="small"
            dataSource={compare.ranking}
            renderItem={(item) => {
              const symbol = String(item.symbol || '--')
              const state = executionStateMeta(String(item.execution_state || ''))
              return (
                <List.Item>
                  <Space wrap style={{ justifyContent: 'space-between', width: '100%' }}>
                    <Typography.Text strong>
                      #{String(item.rank || '--')} {symbol}
                    </Typography.Text>
                    <Space wrap>
                      <Tag color={state.color}>{state.label}</Tag>
                      <Tag>综合分 {typeof item.final_score === 'number' ? item.final_score.toFixed(2) : '--'}</Tag>
                      <Tag>风险 {riskLabel(String(item.risk_level || ''))}</Tag>
                    </Space>
                  </Space>
                </List.Item>
              )
            }}
          />
        ) : null}
      </Space>
    </Card>
  )
}
