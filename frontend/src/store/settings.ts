export type RiskProfile = 'conservative' | 'normal' | 'aggressive'

const RISK_KEY = 'gp_risk_profile'

export function getRiskProfile(): RiskProfile {
  try {
    const v = localStorage.getItem(RISK_KEY)
    if (v === 'conservative' || v === 'normal' || v === 'aggressive') return v
  } catch {}
  return 'normal'
}

export function setRiskProfile(v: RiskProfile) {
  try { localStorage.setItem(RISK_KEY, v) } catch {}
}

