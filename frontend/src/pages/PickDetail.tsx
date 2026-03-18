import { useEffect, useMemo, useState } from 'react'
import { useParams, useLocation } from 'react-router-dom'
import { Alert, Card, Descriptions, Space, Tag, Typography } from 'antd'
import { getPickDetail } from '../api/client'

const { Text, Title } = Typography

type PickItem = {
  symbol: string
  name?: string
  strategy?: string
  strategy_label?: string
  thesis?: string
  price_ref?: number
  entry_zone?: [number, number]
  stop?: number
  take_profit?: number[]
  reward_risk?: number
  execution_state?: string
  confidence?: number
  reliability_score?: number
  final_score?: number
  risk_flags?: string[]
  invalidation?: string[]
}

function extractPick(item: Record<string, unknown> | null | undefined): PickItem | null {
  if (!item) return null
  const g = (k: string) => item[k] as any
  const z = g('entry_zone');
  const take = g('take_profit');
  return {
    symbol: String(g('symbol') || ''),
    name: g('name') != null ? String(g('name')) : undefined,
    strategy: g('strategy') != null ? String(g('strategy')) : undefined,
    strategy_label: g('strategy_label') != null ? String(g('strategy_label')) : undefined,
    thesis: g('thesis') != null ? String(g('thesis')) : undefined,
    price_ref: typeof g('price_ref') === 'number' ? g('price_ref') : undefined,
    entry_zone: Array.isArray(z) && z.length >= 2 ? [Number(z[0]), Number(z[1])] : undefined,
    stop: typeof g('stop') === 'number' ? g('stop') : undefined,
    take_profit: Array.isArray(take) ? (take as unknown[]).map((v) => Number(v as number)) : undefined,
    reward_risk: typeof g('reward_risk') === 'number' ? g('reward_risk') : undefined,
    execution_state: g('execution_state') != null ? String(g('execution_state')) : undefined,
    confidence: typeof g('confidence') === 'number' ? g('confidence') : undefined,
    reliability_score: typeof g('reliability_score') === 'number' ? g('reliability_score') : undefined,
    final_score: typeof g('final_score') === 'number' ? g('final_score') : undefined,
    risk_flags: Array.isArray(g('risk_flags')) ? (g('risk_flags') as unknown[]).map((x) => String(x)) : undefined,
    invalidation: Array.isArray(g('invalidation')) ? (g('invalidation') as unknown[]).map((x) => String(x)) : undefined,
  }
}

export default function PickDetail() {
  const { symbol = '' } = useParams()
  const loc = useLocation()
  const params = useMemo(() => new URLSearchParams(loc.search), [loc.search])
  const runId = useMemo(() => params.get('run_id') || undefined, [params])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [item, setItem] = useState<PickItem | null>(null)

  useEffect(() => {
    async function load() {
      if (!symbol) return
      setLoading(true); setError(null)
      try {
        const d = await getPickDetail({ symbol, run_id: runId })
        const p = extractPick(d.item as Record<string, unknown>)
        setItem(p)
      } catch (e: any) {
        setError(e?.message || String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [symbol, runId])

  const title = useMemo(() => (item ? `${item.symbol}${item.name ? ` · ${item.name}` : ''}` : symbol), [item, symbol])

  return (
    <Card title={title} loading={loading} extra={runId ? <Tag color="geekblue">run {runId}</Tag> : null}>
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 8 }} />}
      {!item && !loading && <Text type="secondary">暂无详情</Text>}
      {item && (
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Space size={[8, 8]} wrap>
            {item.strategy_label && <Tag color="blue">{item.strategy_label}</Tag>}
            {item.execution_state && <Tag color={item.execution_state === 'actionable' ? 'green' : 'default'}>{item.execution_state}</Tag>}
            {typeof item.confidence === 'number' && <Tag color="purple">conf {item.confidence.toFixed(2)}</Tag>}
            {typeof item.reliability_score === 'number' && <Tag>rel {item.reliability_score.toFixed(2)}</Tag>}
            {typeof item.final_score === 'number' && <Tag color="gold">score {item.final_score.toFixed(2)}</Tag>}
          </Space>
          {item.thesis && (
            <div>
              <Title level={5} style={{ marginTop: 0 }}>Thesis</Title>
              <Text>{item.thesis}</Text>
            </div>
          )}
          <Descriptions size="small" column={2}>
            {typeof item.price_ref === 'number' && <Descriptions.Item label="现价">{item.price_ref.toFixed(2)}</Descriptions.Item>}
            {Array.isArray(item.entry_zone) && <Descriptions.Item label="买点">{item.entry_zone.map((v) => Number(v).toFixed(2)).join(' / ')}</Descriptions.Item>}
            {typeof item.stop === 'number' && <Descriptions.Item label="止损">{item.stop.toFixed(2)}</Descriptions.Item>}
            {Array.isArray(item.take_profit) && <Descriptions.Item label="止盈">{item.take_profit.map((v) => Number(v).toFixed(2)).join(' / ')}</Descriptions.Item>}
            {typeof item.reward_risk === 'number' && <Descriptions.Item label="RR">{item.reward_risk.toFixed(2)}</Descriptions.Item>}
          </Descriptions>
          {(Array.isArray(item.risk_flags) && item.risk_flags.length > 0) && (
            <div>
              <Text type="secondary">风险: {item.risk_flags.join('，')}</Text>
            </div>
          )}
          {(Array.isArray(item.invalidation) && item.invalidation.length > 0) && (
            <div>
              <Text type="secondary">失效条件: {item.invalidation.join('，')}</Text>
            </div>
          )}
        </Space>
      )}
    </Card>
  )
}
