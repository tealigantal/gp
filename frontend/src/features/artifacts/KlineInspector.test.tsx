import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SelectedArtifactProvider, useSelectedArtifact } from './useSelectedArtifact'
import KlineInspector from './KlineInspector'
import RecommendationDetail from '../recommendation/RecommendationDetail'

function Host() {
  const { openKline } = useSelectedArtifact()
  const artifact = {
    id: 'a1', as_of: null, timezone: 'Asia/Shanghai', tradeable: true,
    picks: [{ symbol: '600519', name: '贵州茅台', trade_plan: { bands: { S1: 1, R1: 2 } }, chip: { model_used: 'mock' } }]
  } as any
  return (
    <div>
      <RecommendationDetail artifact={artifact} onShowKline={(s) => openKline(s, { bands: artifact.picks[0].trade_plan.bands, chip: artifact.picks[0].chip })} />
      <KlineInspector />
    </div>
  )
}

describe('KlineInspector', () => {
  it('opens and shows symbol', async () => {
    // polyfill matchMedia for antd responsive
    ;(window as any).matchMedia = (window as any).matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    render(<SelectedArtifactProvider><Host /></SelectedArtifactProvider>)
    const link = screen.getByText('查看K线')
    fireEvent.click(link)
    expect(await screen.findByText(/K线 · 600519/)).toBeInTheDocument()
  })
})
vi.mock('../../components/KlineChart', () => ({ default: () => <div>MOCK-KLINE</div> }))
