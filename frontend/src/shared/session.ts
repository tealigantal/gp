const KEY = 'gp.frontend.sessionId'

function randomId() {
  return `session_${Math.random().toString(36).slice(2, 10)}`
}

export function loadSessionId() {
  const existing = window.localStorage.getItem(KEY)?.trim()
  if (existing) return existing
  const next = randomId()
  window.localStorage.setItem(KEY, next)
  return next
}

export function saveSessionId(sessionId: string) {
  window.localStorage.setItem(KEY, sessionId)
}

export function newSessionId() {
  const next = randomId()
  saveSessionId(next)
  return next
}

export function newClientTurnId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `turn_${crypto.randomUUID()}`
  }
  return `turn_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}
