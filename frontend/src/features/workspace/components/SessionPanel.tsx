import { Card, Descriptions, Empty, List, Space, Tag, Typography } from 'antd'
import type { SessionResponse } from '../../../shared/contracts'
import { compactJson, fmtTime } from '../../../shared/format'

interface SessionPanelProps {
  session?: SessionResponse
}

export function SessionPanel({ session }: SessionPanelProps) {
  if (!session) {
    return <Card><Empty description="Session 未加载" /></Card>
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title="Session Truth">
        <Descriptions size="small" column={1}>
          <Descriptions.Item label="active_run">{session.session.active_run_id || '—'}</Descriptions.Item>
          <Descriptions.Item label="previous_run">{session.session.previous_run_id || '—'}</Descriptions.Item>
          <Descriptions.Item label="book_version">{session.session.last_seen_book_version || '—'}</Descriptions.Item>
          <Descriptions.Item label="focus_subject">
            <pre className="json-inline">{compactJson(session.session.focus_subject)}</pre>
          </Descriptions.Item>
          <Descriptions.Item label="compare_set">
            {session.session.compare_set.length ? session.session.compare_set.map((symbol) => <Tag key={symbol}>{symbol}</Tag>) : '—'}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card size="small" title="Recent Claims">
        {session.recent_claims.length === 0 ? (
          <Empty description="暂无 claims" />
        ) : (
          <List
            size="small"
            dataSource={session.recent_claims}
            renderItem={(claim) => (
              <List.Item>
                <Space direction="vertical" size={2} style={{ width: '100%' }}>
                  <Typography.Text strong>
                    {claim.subject_type}:{claim.subject_id} · {claim.predicate}
                  </Typography.Text>
                  <Typography.Text type="secondary">{fmtTime(claim.created_at)}</Typography.Text>
                  <pre className="json-inline">{compactJson(claim.value)}</pre>
                </Space>
              </List.Item>
            )}
          />
        )}
      </Card>
    </Space>
  )
}
