import ReactECharts from 'echarts-for-react'
import { useQuery } from '@tanstack/react-query'
import { ohlcv } from '../api/client'

export default function KlineChart({ symbol, overlay }: { symbol: string; overlay?: { bands?: any; chip?: any } }) {
  const q = useQuery({
    queryKey: ['ohlcv', symbol],
    queryFn: () => ohlcv(symbol, { limit: 120 }),
    enabled: !!symbol
  })
  if (!symbol) return null
  if (q.isLoading || !q.data) return null
  const dates = q.data.bars.map((b) => b.date)
  const values = q.data.bars.map((b) => [b.open, b.close, b.low, b.high])
  const marks: any[] = []
  try {
    if (overlay && overlay.bands) {
      const b: any = overlay.bands
      if (b.S1 != null) marks.push({ yAxis: Number(b.S1), name: 'S1' })
      if (b.S2 != null) marks.push({ yAxis: Number(b.S2), name: 'S2' })
      if (b.R1 != null) marks.push({ yAxis: Number(b.R1), name: 'R1' })
      if (b.R2 != null) marks.push({ yAxis: Number(b.R2), name: 'R2' })
    }
    if (overlay && overlay.chip) {
      const c: any = overlay.chip
      if (c.band_90_low != null) marks.push({ yAxis: Number(c.band_90_low), name: 'C90L' })
      if (c.avg_cost != null) marks.push({ yAxis: Number(c.avg_cost), name: 'AVG' })
      if (c.band_90_high != null) marks.push({ yAxis: Number(c.band_90_high), name: 'C90H' })
    }
  } catch {}
  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: 24, right: 24, top: 16, bottom: 24 },
    xAxis: { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false } },
    yAxis: { scale: true },
    series: [{ type: 'candlestick', data: values, name: symbol, markLine: marks.length ? { symbol: 'none', lineStyle: { type: 'dashed' }, data: marks } : undefined }]
  }
  return <ReactECharts option={option} style={{ height: 240 }} />
}
