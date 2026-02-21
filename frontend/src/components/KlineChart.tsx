import ReactECharts from 'echarts-for-react'
import { useQuery } from '@tanstack/react-query'
import { ohlcv } from '../api/client'

export default function KlineChart({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ['ohlcv', symbol],
    queryFn: () => ohlcv(symbol, { limit: 120 }),
    enabled: !!symbol
  })
  if (!symbol) return null
  if (q.isLoading || !q.data) return null
  const dates = q.data.bars.map((b) => b.date)
  const values = q.data.bars.map((b) => [b.open, b.close, b.low, b.high])
  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: 24, right: 24, top: 16, bottom: 24 },
    xAxis: { type: 'category', data: dates, boundaryGap: true, axisLine: { onZero: false } },
    yAxis: { scale: true },
    series: [{ type: 'candlestick', data: values, name: symbol }]
  }
  return <ReactECharts option={option} style={{ height: 240 }} />
}

