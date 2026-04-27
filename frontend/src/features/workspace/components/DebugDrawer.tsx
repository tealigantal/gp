import { Collapse, Descriptions, Empty, Tag, Typography } from 'antd'
import type { ChatResponse, SessionResponse } from '../../../shared/contracts'
import { compactJson, fmtTime } from '../../../shared/format'

interface DebugDrawerProps {
  session?: SessionResponse
  latestResponse?: ChatResponse | null
}

export function DebugDrawer({ session, latestResponse }: DebugDrawerProps) {
  return (
    <div>
      <Collapse
        size="small"
        defaultActiveKey={[]}
        items={[
          {
            key: 'debug',
            label: '调试信息入口（折叠） · Session Truth / Claims / Planner Trace',
            children: (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div>
                  <Typography.Text strong>Session Truth</Typography.Text>
                  {session ? (
                    <Descriptions size="small" column={2} style={{ marginTop: 8 }}>
                      <Descriptions.Item label="active_run">{session.session.active_run_id || '-'}</Descriptions.Item>
                      <Descriptions.Item label="previous_run">{session.session.previous_run_id || '-'}</Descriptions.Item>
                      <Descriptions.Item label="book_version">{session.session.last_seen_book_version || '-'}</Descriptions.Item>
                      <Descriptions.Item label="updated_at">{fmtTime(session.session.updated_at)}</Descriptions.Item>
                    </Descriptions>
                  ) : (
                    <Empty description="暂无 session" />
                  )}
                </div>
                <div>
                  <Typography.Text strong>Recent Claims</Typography.Text>
                  {session?.recent_claims?.length ? (
                    <div style={{ marginTop: 8 }}>
                      {session.recent_claims.slice(0, 5).map((c) => (
                        <div key={c.claim_id} style={{ marginBottom: 8 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <Tag>
                              {c.subject_type}:{c.subject_id}
                            </Tag>
                            <Tag>{c.predicate}</Tag>
                            <Typography.Text type="secondary">{fmtTime(c.created_at)}</Typography.Text>
                          </div>
                          <pre className="json-inline">{compactJson(c.value)}</pre>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty description="暂无 claims" />
                  )}
                </div>
                <div>
                  <Typography.Text strong>Planner Trace</Typography.Text>
                  {latestResponse?.planner_trace ? (
                    <pre className="json-block" style={{ marginTop: 8 }}>
                      {JSON.stringify(latestResponse.planner_trace, null, 2)}
                    </pre>
                  ) : (
                    <Empty description="暂无 trace" />
                  )}
                </div>
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
