import React from 'react'
import { Card, List, Typography, Tag, Space } from 'antd'

export default function RunChangeCard(props: { summary_reason?: string; payload?: any; onFocus?: (symbol: string) => void }) {
  const { summary_reason, payload, onFocus } = props
  const added: string[] = Array.isArray(payload?.added_symbols) ? payload.added_symbols as string[] : []
  const removed: string[] = Array.isArray(payload?.removed_symbols) ? payload.removed_symbols as string[] : []
  return (
    <Card size="small" title="推荐变化说明">
      <Typography.Text type="secondary">{summary_reason || '已对比本轮与上一轮。'}</Typography.Text>
      {(added.length > 0 || removed.length > 0) && (
        <div style={{ marginTop: 8 }}>
          {added.length > 0 && (
            <div>
              新增：<Space size={6}>{added.map((s) => <Tag key={s} color="green" onClick={() => onFocus?.(s)} style={{ cursor: 'pointer' }}>{s}</Tag>)}</Space>
            </div>
          )}
          {removed.length > 0 && (
            <div style={{ marginTop: 4 }}>
              移除：<Space size={6}>{removed.map((s) => <Tag key={s} color="red" onClick={() => onFocus?.(s)} style={{ cursor: 'pointer' }}>{s}</Tag>)}</Space>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
