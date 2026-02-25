import { Card } from 'antd'
import KlineChart from './KlineChart'
import { syncManager } from '../sync/SyncManager'

export default function KlineCard({ symbol, conversationId }: { symbol: string; conversationId?: string | null }) {
  if (!symbol) return null
  let overlay: any = undefined
  try {
    const cid = conversationId || syncManager.currentConversationId?.()
    if (cid) {
      const evs = syncManager.messages(cid)
      for (let i = evs.length - 1; i >= 0; i--) {
        const e: any = evs[i]
        if (e?.data?.kind === 'card' && e?.data?.payload?.type === 'recommendation') {
          const picks = e?.data?.payload?.picks || []
          const m = Array.isArray(picks) ? picks.find((p: any) => p?.symbol === symbol) : undefined
          if (m) { overlay = { bands: m?.trade_plan?.bands, chip: m?.chip }; break }
        }
      }
    }
  } catch {}
  return (
    <Card size="small" title={`K线 · ${symbol}`} style={{ margin: '8px 0' }}>
      <KlineChart symbol={symbol} overlay={overlay} />
      <div style={{ color: '#999', fontSize: 12, marginTop: 4 }}>
        数据频率：日线
        {overlay?.chip?.model_used && <> ｜ 筹码来源：{String(overlay.chip.model_used)}</>}
        {overlay?.bands && overlay?.chip && <> ｜ 叠加：关键带 + 筹码</>}
        {!overlay?.bands && !overlay?.chip && <> ｜ 无可用叠加数据（strict 模式下不会伪造）</>}
      </div>
    </Card>
  )
}
