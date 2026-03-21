import { Card, List, Space, Tag, Typography } from 'antd'
import type { RecommendationArtifact } from '../../api/contracts'

export default function RecommendationDetail({ artifact, onShowKline, onAsk, onFocus }: { artifact: RecommendationArtifact; onShowKline?: (symbol: string) => void; onAsk?: (text: string) => void; onFocus?: (symbol: string) => void }) {
  if (artifact.artifact_version === 'v2' && artifact.v2) {
    const art = artifact.v2
    const items = Array.isArray(art.items) ? art.items : []
    const tradeable = !!art.tradeable
    const runGate = art.run_gating as any
    return (
      <Card size="small" title={(<Space><span>推荐清单</span><Tag color="blue">{items.length}</Tag>{tradeable ? <Tag color="green">TRADEABLE</Tag> : <Tag color="red">NO-TRADE</Tag>}{art.market_regime && <Tag>{String(art.market_regime)}</Tag>}</Space>)}>
        <div style={{ marginBottom: 8, color: 'rgba(0,0,0,0.65)' }}>
          <div>as_of: {art.as_of || '-'}</div>
          {!!runGate && (<div>run_gating: {String(runGate.decision)}{Array.isArray(runGate.reasons) && runGate.reasons.length ? ` (${runGate.reasons.join(', ')})` : ''}</div>)}
          {!tradeable && art.reason && (<div>reason: {art.reason}</div>)}
        </div>
        <List dataSource={items} renderItem={(it) => (
          <List.Item key={String((it as any).symbol)} actions={[<a key="k" onClick={() => onShowKline?.(String((it as any).symbol))}>查看K线</a>]}>
            <Space direction="vertical" size={2} style={{ width: '100%' }}>
              <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>
                  <a onClick={() => onFocus?.(String((it as any).symbol))}>{String((it as any).symbol)}</a>{(it as any).name ? ` · ${(it as any).name}` : ''}
                </Typography.Text>
                {(it as any).strategy && <Tag color="geekblue">{String((it as any).strategy)}</Tag>}
              </Space>
              {(it as any).thesis && (<Typography.Text type="secondary">{String((it as any).thesis)}</Typography.Text>)}
            </Space>
          </List.Item>
        )} />
      </Card>
    )
  }
  // No legacy fallback: only v2 is supported
  return <Card size="small" title="推荐清单（不支持旧格式）"><Typography.Text type="secondary">仅支持v2</Typography.Text></Card>
}

