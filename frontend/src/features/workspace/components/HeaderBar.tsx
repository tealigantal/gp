import { Button, Space, Tag, Typography } from 'antd'
import type { HealthResponse } from '../../../shared/contracts'

export function HeaderBar({ health, onNewSession }: { health?: HealthResponse; onNewSession: () => void }) {
  const snapshot = health?.current_snapshot as { snapshot_id?: string; tradeable?: boolean } | undefined
  return <div className="header-bar">
    <Space direction="vertical" size={2}>
      <Space><Typography.Text className="brand-chip">GP</Typography.Text><Typography.Title level={3} style={{ margin: 0 }}>荐股对话 Agent</Typography.Title></Space>
      <Typography.Text type="secondary">所有回答固定绑定一份可验证的 RecommendationSnapshot.v1。</Typography.Text>
    </Space>
    <Space><Tag color={snapshot?.tradeable ? 'green' : 'default'}>{snapshot?.tradeable ? '当前快照可交易' : '暂不荐股'}</Tag><Button onClick={onNewSession}>新对话</Button></Space>
  </div>
}
