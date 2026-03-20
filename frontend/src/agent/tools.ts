// Canonical agent tool layer for frontend (LLM orchestration uses backend chat).
// Keep input/output simple and composable.
import { getRecommendV2Gated as getRecommendV2, getPickDetail, getStrategyValidation, getValidationSummary } from '../api/client'

export async function get_market_summary() {
  const v2 = await getRecommendV2()
  return {
    as_of: v2.as_of || null,
    tradeable: !!v2.tradeable,
    regime: v2.market_regime || null,
    gating: v2.run_gating || null,
    themes: v2.themes || [],
  }
}

export async function get_top_picks() {
  const v2 = await getRecommendV2()
  return (v2.items || []).map((it) => ({
    symbol: it.symbol,
    name: it.name,
    strategy: it.strategy_label || it.strategy,
    thesis: it.thesis,
    price: it.price_ref,
    entry: it.entry_zone,
    stop: it.stop,
    take: it.take_profit,
    rr: it.reward_risk,
    execution_state: it.execution_state,
    confidence: it.confidence,
    reliability: it.reliability_score,
    score: it.final_score,
  }))
}

export async function get_pick_detail(symbol: string) {
  const d = await getPickDetail({ symbol })
  const it = (d.item || {}) as Record<string, unknown>
  return {
    symbol: String(it.symbol || symbol),
    name: it.name as string | undefined,
    strategy: (it.strategy_label as string) || (it.strategy as string | undefined),
    thesis: it.thesis as string | undefined,
    price: (typeof it.price_ref === 'number') ? (it.price_ref as number) : undefined,
    entry: Array.isArray(it.entry_zone) ? (it.entry_zone as number[]) : undefined,
    stop: (typeof it.stop === 'number') ? (it.stop as number) : undefined,
    take: Array.isArray(it.take_profit) ? (it.take_profit as number[]) : undefined,
    rr: (typeof it.reward_risk === 'number') ? (it.reward_risk as number) : undefined,
    execution_state: it.execution_state as string | undefined,
    confidence: (typeof it.confidence === 'number') ? (it.confidence as number) : undefined,
    reliability: (typeof it.reliability_score === 'number') ? (it.reliability_score as number) : undefined,
    score: (typeof it.final_score === 'number') ? (it.final_score as number) : undefined,
  }
}

// compare_symbols removed from primary UI flow

export async function get_strategy_health(strategy: string) {
  return getStrategyValidation(strategy)
}

export async function get_validation_summary() {
  return getValidationSummary()
}
