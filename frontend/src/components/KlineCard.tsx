import { Card } from 'antd'
import KlineChart from './KlineChart'

export default function KlineCard({ symbol }: { symbol: string }) {
  if (!symbol) return null
  return (
    <Card size="small" title={`K线 · ${symbol}`} style={{ margin: '8px 0' }}>
      <KlineChart symbol={symbol} />
    </Card>
  )
}

