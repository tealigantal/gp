import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import RecommendationCard from './RecommendationCard'

describe('RecommendationCard typed', () => {
  it('renders artifact picks and bands', () => {
    // polyfill matchMedia for antd responsive
    ;(window as any).matchMedia = (window as any).matchMedia || ((q: string) => ({ matches: false, media: q, onchange: null, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }))
    const artifact = {
      id: 'a1', as_of: null, timezone: 'Asia/Shanghai', tradeable: true,
      picks: [{ symbol: '000001', name: '平安银行', theme: '银行', champion: { strategy: 'value', score: 87 }, trade_plan: { bands: { S1: 10, R1: 12 }, entry: ['10.5'], stop: '9.8', take: ['11.8', '12.5'] } }]
    } as any
    render(<RecommendationCard artifact={artifact} />)
    expect(screen.getByText(/000001/)).toBeInTheDocument()
    expect(screen.getAllByText(/银行/).length).toBeGreaterThan(0)
    expect(screen.getByText(/关键带/)).toBeInTheDocument()
    expect(screen.getByText(/买点/)).toBeInTheDocument()
  })
})
