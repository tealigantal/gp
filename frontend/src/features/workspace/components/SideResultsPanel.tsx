import { Card, Empty, List, Space, Tag, Typography } from 'antd'
import type { SideResult } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'

interface SideResultsPanelProps {
  items: SideResult[]
}

export function SideResultsPanel({ items }: SideResultsPanelProps) {
  return (
    <Card size="small" title="盘中 Side Results">
      {items.length === 0 ? (
        <Empty description="目前没有新的盘中侧边信号" />
      ) : (
        <List
          size="small"
          dataSource={items}
          renderItem={(item) => (
            <List.Item>
              <Space direction="vertical" size={2} style={{ width: '100%' }}>
                <Space wrap>
                  <Typography.Text strong>{item.title}</Typography.Text>
                  {item.symbol ? <Tag>{item.symbol}</Tag> : null}
                  <Tag>{item.kind}</Tag>
                </Space>
                <Typography.Text>{item.body}</Typography.Text>
                <Typography.Text type="secondary">{fmtTime(item.created_at)}</Typography.Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </Card>
  )
}
