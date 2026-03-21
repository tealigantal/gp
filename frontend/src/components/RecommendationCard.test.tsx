import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RecommendationCard from './RecommendationCard'

describe('RecommendationCard typed', () => {
  it('renders artifact picks and bands', () => {
    // polyfill matchMedia for antd responsive
    const w = window as unknown as { matchMedia?: (q: string) => { matches: boolean; media: string; onchange: null; addListener: (h: unknown)=>void; removeListener: (h: unknown)=>void; addEventListener: (t: string, h: unknown)=>void; removeEventListener: (t: string, h: unknown)=>void; dispatchEvent: (e: unknown)=> boolean } }
    w.matchMedia = w.matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    const artifact = {
      id: 'a1', as_of: null, timezone: 'Asia/Shanghai', tradeable: true,
      picks: [{ symbol: '000001', name: '平安银行', theme: '银行', champion: { strategy: 'value', score: 87 }, trade_plan: { bands: { S1: 10, R1: 12 }, entry: ['10.5'], stop: '9.8', take: ['11.8', '12.5'] } }]
    }
    render(<RecommendationCard artifact={artifact} />)
    expect(screen.getByText(/000001/)).toBeInTheDocument()
    expect(screen.getAllByText(/银行/).length).toBeGreaterThan(0)
    expect(screen.getByText(/关键带/)).toBeInTheDocument()
    expect(screen.getByText(/买点/)).toBeInTheDocument()
  })
})
