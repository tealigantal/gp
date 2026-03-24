export type RiskProfile = 'conservative' | 'normal' | 'aggressive'

const RISK_KEY = 'gp_risk_profile'
const FORCE_REFRESH_KEY = 'gp_force_refresh'

export function getRiskProfile(): RiskProfile {
  try {
    const v = localStorage.getItem(RISK_KEY)
    if (v === 'conservative' || v === 'normal' || v === 'aggressive') return v
  } catch (e) { /* ignore */ void e }
  return 'normal'
}

export function setRiskProfile(v: RiskProfile) {
  try { localStorage.setItem(RISK_KEY, v) } catch (e) { /* ignore */ void e }
}

export function getForceRefresh(): boolean {
  try {
    const v = localStorage.getItem(FORCE_REFRESH_KEY)
    return v === '1' || v === 'true'
  } catch (e) { /* ignore */ void e }
  return false
}

export function setForceRefresh(v: boolean) {
  try {
    localStorage.setItem(FORCE_REFRESH_KEY, v ? '1' : '0')
  } catch (e) { /* ignore */ void e }
  try {
    window.dispatchEvent(new CustomEvent('gp_force_refresh_changed'))
  } catch { /* ignore */ }
}

