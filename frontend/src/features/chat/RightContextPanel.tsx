import React from 'react'
import { Card, Descriptions, Tag, Typography } from 'antd'

export default function RightContextPanel({ panel }: { panel?: Record<string, unknown> | null }) {
  const p = (panel || {}) as Record<string, any>
  const runId = p.active_run_id as string | undefined
  const prevRun = p.previous_run_id as string | undefined
  const focus = p.focus_symbol as string | undefined
  const top = Array.isArray(p.top_symbols) ? (p.top_symbols as unknown[]).map((s) => String(s)) : undefined
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card size="small" title="上下文状态">
        <Descriptions size="small" column={1} bordered>
          {runId && (
            <Descriptions.Item label="本轮 run_id">{runId}</Descriptions.Item>
          )}
          {prevRun && (
            <Descriptions.Item label="上轮 run_id">{prevRun}</Descriptions.Item>
          )}
          {focus && (
            <Descriptions.Item label="焦点标的"><Tag>{focus}</Tag></Descriptions.Item>
          )}
          {top && top.length > 0 && (
            <Descriptions.Item label="Top">
              <Typography.Text>{top.join(' / ')}</Typography.Text>
            </Descriptions.Item>
          )}
          {p.reused_run != null && (
            <Descriptions.Item label="复用run">{p.reused_run ? '是' : '否'}</Descriptions.Item>
          )}
          {p.stale != null && (
            <Descriptions.Item label="是否陈旧">{p.stale ? '是' : '否'}</Descriptions.Item>
          )}
          {p.cache_level && (
            <Descriptions.Item label="缓存层级">{String(p.cache_level)}</Descriptions.Item>
          )}
          {p.refresh_reason && (
            <Descriptions.Item label="刷新原因">{String(p.refresh_reason)}</Descriptions.Item>
          )}
          {p.planner_intent && (
            <Descriptions.Item label="Planner意图">{String(p.planner_intent)}</Descriptions.Item>
          )}
          {p.executor_path && (
            <Descriptions.Item label="执行分支">{String(p.executor_path)}</Descriptions.Item>
          )}
        </Descriptions>
      </Card>
    </div>
  )
}

