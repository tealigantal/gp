import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Button, Card, Input, List, Space, Tag, Typography } from 'antd'
import { compareSymbols, getPickDetail } from '../api/client'

const { Text, Title } = Typography

export default function Compare() {
  const loc = useLocation()
  const nav = useNavigate()
  const [symbolsInput, setSymbolsInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const [winner, setWinner] = useState<string | null>(null)
  const [items, setItems] = useState<Array<{ symbol: string; confidence?: number; reliability?: number; score?: number }>>([])

  const params = useMemo(() => new URLSearchParams(loc.search), [loc.search])
  const initialSymbols = useMemo(() => params.get('symbols')?.split(',').map((s) => s.trim()).filter(Boolean) || [], [params])
  const runId = useMemo(() => params.get('run_id') || undefined, [params])

  useEffect(() => { if (initialSymbols.length) setSymbolsInput(initialSymbols.join(',')) }, [initialSymbols])

  async function runCompare() {
    const symbols = symbolsInput.split(',').map((s) => s.trim()).filter(Boolean).slice(0, 3)
    if (symbols.length < 2) { setError('至少选择2只'); return }
    setLoading(true); setError(null)
    try {
      const [cmp] = await Promise.all([
        compareSymbols({ symbols, run_id: runId }),
      ])
      setSummary(cmp.summary || null)
      setWinner(cmp.winner_symbol || null)
      const details = await Promise.all(symbols.map(async (s) => {
        try {
          const d = await getPickDetail({ symbol: s, run_id: runId })
          const it = (d.item || {}) as Record<string, unknown>
          const confidence = typeof it.confidence === 'number' ? (it.confidence as number) : undefined
          const reliability = typeof it.reliability_score === 'number' ? (it.reliability_score as number) : undefined
          const score = typeof it.final_score === 'number' ? (it.final_score as number) : undefined
          return { symbol: s, confidence, reliability, score }
        } catch { return { symbol: s } }
      }))
      setItems(details)
      const q = new URLSearchParams()
      q.set('symbols', symbols.join(','))
      if (runId) q.set('run_id', runId)
      nav(`/compare?${q.toString()}`, { replace: true })
    } catch (e: any) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card title="对比">
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 8 }} />}
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input value={symbolsInput} onChange={(e) => setSymbolsInput(e.target.value)} placeholder="输入2~3个代码，用逗号分隔，如 600519,000001" onPressEnter={runCompare} />
        <Button type="primary" onClick={runCompare} loading={loading}>对比</Button>
      </Space.Compact>
      {summary && (
        <div style={{ marginBottom: 12 }}>
          <Title level={5} style={{ marginTop: 0 }}>结论</Title>
          <Text>{summary}</Text>
        </div>
      )}
      {winner && (
        <div style={{ marginBottom: 12 }}>
          <Tag color="green">胜出: {winner}</Tag>
        </div>
      )}
      <List
        header={<div>候选</div>}
        dataSource={items}
        renderItem={(it) => (
          <List.Item key={it.symbol} actions={[<a key="detail" onClick={() => {
            const q = new URLSearchParams(); if (runId) q.set('run_id', runId); nav(`/pick/${encodeURIComponent(it.symbol)}?${q.toString()}`)
          }}>详情</a>] }>
            <Space>
              <Text strong>{it.symbol}</Text>
              {typeof it.confidence === 'number' && <Tag color="purple">conf {it.confidence.toFixed(2)}</Tag>}
              {typeof it.reliability === 'number' && <Tag>rel {it.reliability.toFixed(2)}</Tag>}
              {typeof it.score === 'number' && <Tag color="gold">score {it.score.toFixed(2)}</Tag>}
            </Space>
          </List.Item>
        )}
      />
    </Card>
  )}
