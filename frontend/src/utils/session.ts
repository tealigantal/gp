export const LAST_SID_KEY = 'gp:lastSid'

export function getOrCreateSessionId(): string {
  const url = new URL(window.location.href)
  // unify on 'cid'; accept legacy 'sid' and upgrade URL
  const cidParam = url.searchParams.get('cid')
  const legacySid = url.searchParams.get('sid')
  let sid = (cidParam || legacySid || localStorage.getItem(LAST_SID_KEY) || '').trim()
  if (!sid) sid = newSid()
  // persist and reflect in URL as cid only
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch (e) { /* ignore */ void e }
  try {
    if (url.searchParams.get('cid') !== sid) {
      url.searchParams.set('cid', sid)
    }
    if (url.searchParams.has('sid')) {
      url.searchParams.delete('sid')
    }
    // IMPORTANT: preserve existing history.state (React Router stores its own keys in it).
    // Replacing it with `{}` can break navigation/back/forward behavior.
    window.history.replaceState(window.history.state, '', url.toString())
  } catch (e) { /* ignore */ void e }
  return sid
}

export function setSessionId(sid: string) {
  const url = new URL(window.location.href)
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch (e) { /* ignore */ void e }
  try {
    url.searchParams.set('cid', sid)
    if (url.searchParams.has('sid')) url.searchParams.delete('sid')
    // Preserve router-managed state.
    window.history.replaceState(window.history.state, '', url.toString())
  } catch (e) { /* ignore */ void e }
}

export function newSid() {
  // Avoid collisions (events/session ids must be globally unique on server).
  try {
    const uuid = crypto?.randomUUID?.()
    if (uuid) return `sess-${uuid}`
  } catch (e) { /* ignore */ void e }
  return `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
