import { Card, List, Space, Tag, Typography } from 'antd'
import type { RunChangeArtifact } from '../../../shared/contracts'

interface RunChangeMessageCardProps {
  text: string
  change: RunChangeArtifact
}

export function RunChangeMessageCard({ text, change }: RunChangeMessageCardProps) {
  const rows = [
    ...change.added.map((symbol) => `新增：${symbol}`),
    ...change.removed.map((symbol) => `移除：${symbol}`),
    ...change.rank_changes.map((item) => `${item.symbol} 排名 ${item.from_rank} -> ${item.to_rank}`),
  ]

  return (
    <Card size="small" className="detail-card">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space wrap>
          <Tag color="geekblue">本轮 vs 上轮</Tag>
          {change.current_run_id ? <Tag>{change.current_run_id}</Tag> : null}
        </Space>

        <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{text}</Typography.Paragraph>

        {rows.length > 0 ? (
          <List size="small" dataSource={rows} renderItem={(item) => <List.Item>{item}</List.Item>} />
        ) : (
          <Typography.Text type="secondary">这两轮之间暂时没有明显的新增、移除或排名变化。</Typography.Text>
        )}
      </Space>
    </Card>
  )
}
