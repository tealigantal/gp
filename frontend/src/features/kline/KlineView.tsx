import { Card } from 'antd'
import KlineChart from '../../components/KlineChart'
import type { KlineOverlay } from '../artifacts/useSelectedArtifact'

export default function KlineView({ symbol, overlay }: { symbol: string; overlay?: KlineOverlay }) {
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

