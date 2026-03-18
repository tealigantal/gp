import { useMemo } from 'react'
import WorkbenchLayout from '../components/WorkbenchLayout'
import { useWorkbench } from '../features/workbench/useWorkbench'
import { Tag, Button, message, Card, List, Space, Descriptions, Typography, Alert } from 'antd'
import { useLocation } from 'react-router-dom'

const { Text } = Typography

function StatusTag({ s }: { s: 'allow'|'degraded'|'blocked'|undefined }) {
  if (s==='blocked') return <Tag color="red">Blocked</Tag>
  if (s==='degraded') return <Tag color="orange">Degraded</Tag>
  return <Tag color="green">Allow</Tag>
}

function Scores({ final_score, confidence, reliability }: { final_score?: number; confidence?: number; reliability?: number }) {
  return (
    <Space size={16}>
      <Text type="secondary">Score: {final_score!=null ? final_score.toFixed(2) : '-'}</Text>
      <Text type="secondary">Conf: {confidence!=null ? confidence.toFixed(2) : '-'}</Text>
      <Text type="secondary">Rel: {reliability!=null ? reliability.toFixed(2) : '-'}</Text>
    </Space>
  )
}

export default function Workbench() {
  const loc = useLocation()
  const params = useMemo(() => new URLSearchParams(loc.search), [loc.search])
  const runId = useMemo(() => params.get('run_id') || undefined, [params])
  const { loading, error, vm, admit, reject, cancel } = useWorkbench({ run_id: runId })

  const recList = useMemo(() => vm?.recs || [], [vm])
  const intentsPreview = vm?.intentsPreview || []
  const pending = (vm?.raw?.portfolio as any)?.pending_intents || []
  const events = vm?.raw?.execution_events || []

  const left = (
    <div style={{ paddingRight: 8, display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div className="workbench-scroll">
        <Card size="small" title="System Summary" bordered={false} style={{ marginBottom: 12 }} extra={runId ? <Tag color="geekblue">run {runId}</Tag> : null}>
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 8 }} />}
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="as_of">{vm?.as_of || '-'}</Descriptions.Item>
            <Descriptions.Item label="run gating"><StatusTag s={vm?.run_status as any} /></Descriptions.Item>
            <Descriptions.Item label="warnings">{(vm?.raw?.warnings || []).length}</Descriptions.Item>
          </Descriptions>
        </Card>
        <Card size="small" title="Validation / Health" bordered={false}>
          <Space size={12} wrap>
            <Tag color="green">healthy {vm?.validationSummary.healthy}</Tag>
            <Tag color="orange">degraded {vm?.validationSummary.degraded}</Tag>
            <Tag color="red">killed {vm?.validationSummary.killed}</Tag>
            <Tag color="gold">wf missing {vm?.validationSummary.wf_missing}</Tag>
            <Tag color={vm?.validationSummary.live_shadow_ok ? 'green' : 'default'}>live shadow {vm?.validationSummary.live_shadow_ok ? 'ok' : 'n/a'}</Tag>
          </Space>
        </Card>
      </div>
    </div>
  )

  const center = (
    <div className="workbench-scroll" style={{ display: 'grid', gridTemplateRows: 'min-content min-content minmax(0, 1fr)', gap: 12, minHeight: 0 }}>
      <Card size="small" title="Recommendations" loading={loading}>
        <div className="workbench-scroll">
          <List
            dataSource={recList}
            renderItem={(it) => (
              <List.Item extra={<Scores final_score={it.final_score} confidence={it.confidence} reliability={it.reliability} />}>
                <Space direction="vertical">
                  <Space align="center" size={12}>
                    <Text strong>{it.symbol}</Text>
                    <StatusTag s={it.status} />
                    {it.actionable ? <Tag color="blue">actionable</Tag> : <Tag>not actionable</Tag>}
                  </Space>
                  {it.reasons && it.reasons.length>0 && (
                    <Text type="secondary">{it.reasons.slice(0,2).join('; ')}</Text>
                  )}
                </Space>
              </List.Item>
            )}
          />
        </div>
      </Card>
      <Card size="small" title="Intent Review (preview from recommend)">
        <div className="workbench-scroll">
          <List
            dataSource={intentsPreview}
            renderItem={(it:any) => (
              <List.Item
                actions={[
                  <Button size="small" type="primary" onClick={async()=>{ await admit(String(it.run_id), String(it.as_of), String(it.symbol)); message.success('Admitted'); }}>Admit</Button>,
                  <Button size="small" danger onClick={async()=>{ await reject(String(it.run_id), String(it.as_of), String(it.symbol)); message.success('Rejected'); }}>Reject</Button>,
                ]}
              >
                <Space direction="vertical">
                  <Space align="center" size={12}>
                    <Text strong>{it.symbol}</Text>
                    <StatusTag s={(it.gating_decision?.decision) as any} />
                  </Space>
                  <Space size={12}>
                    <Text type="secondary">priority: {it.priority?.toFixed?.(2) ?? '-'}</Text>
                    <Text type="secondary">sizing: {it.sizing_hint?.toFixed?.(2) ?? '-'}</Text>
                  </Space>
                </Space>
              </List.Item>
            )}
          />
        </div>
      </Card>
      <div style={{ display:'grid', gridTemplateColumns:'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, minHeight:0 }}>
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <Card size="small" title="Portfolio Summary" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <Space size={12}>
              <Tag>positions {vm?.portfolioSummary.positions}</Tag>
              <Tag color="blue">pending {vm?.portfolioSummary.pending}</Tag>
              <Tag color="purple">events {vm?.portfolioSummary.events}</Tag>
            </Space>
            <div className="workbench-scroll" style={{ marginTop: 8 }}>
              <List size="small" header={<div>Pending Intents</div>} dataSource={pending}
                renderItem={(it:any)=> (
                  <List.Item actions={[<Button size="small" onClick={async()=>{ await cancel(String(it.intent_id)); message.success('Cancelled'); }}>Cancel</Button>] }>
                    <Space size={12}>
                      <Text strong>{it.symbol}</Text>
                      <Text type="secondary">status: {it.status}</Text>
                      <Text type="secondary">priority: {it.priority?.toFixed?.(2) ?? '-'}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </div>
          </Card>
        </div>
        <div style={{ minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <Card size="small" title="Recent Execution Events" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            <div className="workbench-scroll">
              <List size="small" dataSource={events}
                renderItem={(e:any)=> (
                  <List.Item>
                    <Space size={12}>
                      <Text strong>{e.event_type}</Text>
                      <Text>{e.symbol}</Text>
                      <Text type="secondary">{e.timestamp}</Text>
                    </Space>
                  </List.Item>
                )}
              />
            </div>
          </Card>
        </div>
      </div>
    </div>
  )

  const right = (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div className="workbench-scroll">
        <Card size="small" title="研究提示" bordered={false}>
          <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>
            本页为模拟/研究页，提供推荐快照与健康概览，不再作为首页执行台。
          </Typography.Paragraph>
        </Card>
      </div>
    </div>
  )

  return <WorkbenchLayout left={left} center={center} right={right} />
}
