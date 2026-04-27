import { Card, Descriptions, Space, Tag, Typography } from 'antd'
import type { PickDetailArtifact } from '../../../shared/contracts'

interface PickDetailMessageCardProps {
  detail: PickDetailArtifact
  text: string
}

export function PickDetailMessageCard({ detail, text }: PickDetailMessageCardProps) {
  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="blue">单票详情</Tag>
          <Tag>{detail.symbol}</Tag>
          {detail.rank ? <Tag>第 {detail.rank} 只</Tag> : null}
          {detail.execution_state ? <Tag>{detail.execution_state}</Tag> : null}
        </Space>
        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>
        <Descriptions size="small" column={2}>
          <Descriptions.Item label="买入区">{detail.entry_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止损 / 失效">{detail.stop_text || detail.invalidation || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="止盈">{detail.take_text || '待确认'}</Descriptions.Item>
          <Descriptions.Item label="风险">{detail.risk_level || 'medium'}</Descriptions.Item>
        </Descriptions>
      </Space>
    </Card>
  )
}
