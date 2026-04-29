import { Collapse, Descriptions, Empty, Tag, Typography } from 'antd'
import type { ChatResponse, SessionDiagnosticsResponse, SessionResponse } from '../../../shared/contracts'
import { compactJson, fmtTime } from '../../../shared/format'

interface DebugDrawerProps {
  session?: SessionResponse
  diagnostics?: SessionDiagnosticsResponse
  latestResponse?: ChatResponse | null
}

export function DebugDrawer({ session, diagnostics, latestResponse }: DebugDrawerProps) {
  return (
    <div>
      <Collapse
        size="small"
        defaultActiveKey={[]}
        items={[
          {
            key: 'debug',
            label: 'Diagnostics / Session Truth',
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
                    <Empty description="No session state" />
                  )}
                </div>

                <div>
                  <Typography.Text strong>Safe Diagnostics</Typography.Text>
                  {diagnostics ? (
                    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <Descriptions size="small" column={2}>
                        <Descriptions.Item label="focus_symbol">{diagnostics.focus.last_focus_symbol || '-'}</Descriptions.Item>
                        <Descriptions.Item label="focus_rank">{diagnostics.focus.last_focus_rank ?? '-'}</Descriptions.Item>
                        <Descriptions.Item label="active_run">{diagnostics.focus.active_run_id || '-'}</Descriptions.Item>
                        <Descriptions.Item label="previous_run">{diagnostics.focus.previous_run_id || '-'}</Descriptions.Item>
                      </Descriptions>

                      <div>
                        <Typography.Text type="secondary">compare_set</Typography.Text>
                        <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {diagnostics.focus.compare_set.length ? (
                            diagnostics.focus.compare_set.map((symbol) => <Tag key={symbol}>{symbol}</Tag>)
                          ) : (
                            <Tag>empty</Tag>
                          )}
                        </div>
                      </div>

                      <div>
                        <Typography.Text type="secondary">recent assistant messages</Typography.Text>
                        {diagnostics.assistant_messages.length ? (
                          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                            {diagnostics.assistant_messages.map((message, index) => (
                              <div
                                key={`${message.turn_id || 'turn'}-${index}`}
                                style={{
                                  border: '1px solid var(--border-soft)',
                                  borderRadius: 12,
                                  padding: 10,
                                }}
                              >
                                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 6 }}>
                                  <Tag color={index === 0 ? 'blue' : 'default'}>{message.message_kind || 'unknown'}</Tag>
                                  {message.symbol ? <Tag>{message.symbol}</Tag> : null}
                                  {message.run_action ? <Tag>{message.run_action}</Tag> : null}
                                  <Typography.Text type="secondary">{fmtTime(message.created_at)}</Typography.Text>
                                </div>
                                <Typography.Paragraph style={{ marginBottom: 6 }}>
                                  {message.narrative_text || 'No narrative text'}
                                </Typography.Paragraph>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                                  {(message.followup_suggestions || []).map((item) => (
                                    <Tag key={item}>{item}</Tag>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <Empty description="No assistant diagnostics" />
                        )}
                      </div>
                    </div>
                  ) : (
                    <Empty description="No diagnostics snapshot" />
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
                    <Empty description="No claims" />
                  )}
                </div>

                <div>
                  <Typography.Text strong>Grounding Summary</Typography.Text>
                  {latestResponse?.grounding_summary ? (
                    <pre className="json-block" style={{ marginTop: 8 }}>
                      {JSON.stringify(latestResponse.grounding_summary, null, 2)}
                    </pre>
                  ) : (
                    <Empty description="No grounding summary" />
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
