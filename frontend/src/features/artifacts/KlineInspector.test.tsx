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
  } as { id: string; as_of: null; timezone: string; tradeable: boolean; picks: Array<{ symbol: string; name?: string; trade_plan: { bands: { S1?: number; R1?: number } }; chip?: { model_used?: string } }> }
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
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    render(<SelectedArtifactProvider><Host /></SelectedArtifactProvider>)
    const link = screen.getByText('查看K线')
    fireEvent.click(link)
    expect(await screen.findByText(/K线 · 600519/)).toBeInTheDocument()
  })
})
vi.mock('../../components/KlineChart', () => ({ default: () => <div>MOCK-KLINE</div> }))
