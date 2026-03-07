import React, { createContext, useContext, useMemo, useState } from 'react'
import type { RecommendationArtifact } from '../../api/contracts'

export type KlineOverlay = {
  bands?: { S1?: number; S2?: number; R1?: number; R2?: number }
  chip?: { model_used?: string }
}

type InspectorState = {
  panel: 'kline' | 'recommendation' | null
  klineSymbol: string | null
  klineOverlay?: KlineOverlay
  recommendation?: RecommendationArtifact | null
  openKline: (symbol: string, overlay?: KlineOverlay) => void
  openRecommendation: (artifact: RecommendationArtifact) => void
  close: () => void
}

const Ctx = createContext<InspectorState | null>(null)

export function SelectedArtifactProvider({ children }: { children: React.ReactNode }) {
  const [panel, setPanel] = useState<'kline' | 'recommendation' | null>(null)
  const [klineSymbol, setKlineSymbol] = useState<string | null>(null)
  const [klineOverlay, setKlineOverlay] = useState<KlineOverlay | undefined>(undefined)
  const [recommendation, setRecommendation] = useState<RecommendationArtifact | null>(null)

  const value = useMemo<InspectorState>(() => ({
    panel,
    klineSymbol,
    klineOverlay,
    recommendation,
    openKline: (symbol, overlay) => { setKlineSymbol(symbol); setKlineOverlay(overlay); setPanel('kline') },
    openRecommendation: (artifact) => { setRecommendation(artifact); setPanel('recommendation') },
    close: () => { setPanel(null) },
  }), [panel, klineSymbol, klineOverlay, recommendation])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useSelectedArtifact() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useSelectedArtifact must be used within SelectedArtifactProvider')
  return v
}

