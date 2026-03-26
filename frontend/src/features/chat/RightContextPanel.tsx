import React, { useState } from 'react'
import { Card, Descriptions, Tag, Typography, Switch, Tooltip, Button, message, InputNumber } from 'antd'
import { getForceRefresh, setForceRefresh } from '../../store/settings'
import { forceRefreshRecommend } from '../../api/client'
import type { ForceRefreshResp } from '../../api/types'

export default function RightContextPanel({ panel, sessionId, onForceRefreshCompleted }: { panel?: Record<string, unknown> | null; sessionId?: string | null; onForceRefreshCompleted?: (res: ForceRefreshResp) => void }) {
  const p = (panel || {}) as Record<string, any>
  const runId = p.active_run_id as string | undefined
  const prevRun = p.previous_run_id as string | undefined
  const focus = p.focus_symbol as string | undefined
  const top = Array.isArray(p.top_symbols) ? (p.top_symbols as unknown[]).map((s) => String(s)) : undefined
  // 不自动打开 K 线，保持纯手动触发（通过“查看K线”）
  const force = getForceRefresh()
  const [loading, setLoading] = useState(false)
  const [days, setDays] = useState<number>(3)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Card size="small" title="上下文状态" extra={
        <Tooltip title="强制刷新K线">
          <Switch size="small" defaultChecked={force} onChange={(v) => setForceRefresh(!!v)} />
        </Tooltip>
      }>
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
        <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
          <InputNumber size="small" min={1} max={10} value={days} onChange={(v) => setDays(Number(v) || 0)} style={{ width: 80 }} />
          <Button type="primary" size="small" loading={loading} disabled={loading}
            onClick={async () => {
              if (!sessionId) { message.warning('无有效会话'); return }
              const d = Number(days)
              if (!Number.isInteger(d) || d < 1 || d > 10) { message.error('请输入 1 到 10 的整数'); return }
              try {
                setLoading(true)
                const res = await forceRefreshRecommend({ session_id: sessionId, days: d })
                message.success(res?.message || '已刷新K线')
                onForceRefreshCompleted?.(res)
              } catch (err: any) {
                const msg = err?.message || '刷新失败'
                message.error(msg)
              } finally {
                setLoading(false)
              }
            }}
          >{loading ? '处理中...' : '刷新K线'}</Button>
        </div>
      </Card>
    </div>
  )
}
