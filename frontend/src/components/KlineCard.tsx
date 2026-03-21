import { Card } from 'antd'
import KlineChart from './KlineChart'

export type KlineOverlay = { bands?: { S1?: number; S2?: number; R1?: number; R2?: number }; chip?: { model_used?: string } }

export default function KlineCard({ symbol, overlay }: { symbol: string; overlay?: KlineOverlay }) {
  if (!symbol) return null
  return (
    <Card size="small" title={`K线 · ${symbol}`} style={{ margin: '8px 0' }}>
      <KlineChart symbol={symbol} overlay={overlay} />
      <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
        数据频率：日线
        {overlay?.chip?.model_used && <> ｜ 筹码来源：{String(overlay.chip.model_used)}</>}
        {overlay?.bands && overlay?.chip && <> ｜ 叠加：关键带 + 筹码</>}
      </div>
    </Card>
  )
}
