import { Card, List, Space, Tag, Typography } from 'antd'
import type { CompareArtifact } from '../../../shared/contracts'

interface CompareMessageCardProps {
  compare: CompareArtifact
  text: string
}

export function CompareMessageCard({ compare, text }: CompareMessageCardProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="geekblue">对比</Tag>
          {compare.leader_symbol ? <Tag>优先 {compare.leader_symbol}</Tag> : null}
        </Space>
        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
        {compare.comparison_points.length > 0 ? (
          <List size="small" dataSource={compare.comparison_points} renderItem={(item) => <List.Item>{item}</List.Item>} />
        ) : null}
      </Space>
    </Card>
  )
}
