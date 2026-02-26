export const LAST_SID_KEY = 'gp:lastSid'

export function getOrCreateSessionId(): string {
  const url = new URL(window.location.href)
  // unify on 'cid'; accept legacy 'sid' and upgrade URL
  const cidParam = url.searchParams.get('cid')
  const legacySid = url.searchParams.get('sid')
  let sid = (cidParam || legacySid || localStorage.getItem(LAST_SID_KEY) || '').trim()
  if (!sid) sid = newSid()
  // persist and reflect in URL as cid only
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch {}
  try {
    if (url.searchParams.get('cid') !== sid) {
      url.searchParams.set('cid', sid)
    }
    if (url.searchParams.has('sid')) {
      url.searchParams.delete('sid')
    }
    window.history.replaceState({}, '', url.toString())
  } catch {}
  return sid
}

export function setSessionId(sid: string) {
  const url = new URL(window.location.href)
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch {}
  try {
    url.searchParams.set('cid', sid)
    if (url.searchParams.has('sid')) url.searchParams.delete('sid')
    window.history.replaceState({}, '', url.toString())
  } catch {}
}

export function newSid() {
  return 'sess-' + Date.now().toString().slice(0, 10)
}
