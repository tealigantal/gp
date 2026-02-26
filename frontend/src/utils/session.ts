export const LAST_SID_KEY = 'gp:lastSid'

export function getOrCreateSessionId(): string {
  const url = new URL(window.location.href)
  // prefer sid, fallback cid
  const sidParam = url.searchParams.get('sid') || url.searchParams.get('cid')
  let sid = sidParam || localStorage.getItem(LAST_SID_KEY) || ''
  sid = (sid || '').trim()
  if (!sid) sid = newSid()
  // persist and reflect in URL as cid
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch {}
  try {
    if (url.searchParams.get('cid') !== sid) {
      url.searchParams.set('cid', sid)
      // maintain other params; do not add sid to avoid duplication
      window.history.replaceState({}, '', url.toString())
    }
  } catch {}
  return sid
}

export function setSessionId(sid: string) {
  const url = new URL(window.location.href)
  try { localStorage.setItem(LAST_SID_KEY, sid) } catch {}
  try {
    url.searchParams.set('cid', sid)
    window.history.replaceState({}, '', url.toString())
  } catch {}
}

export function newSid() {
  return 'sess-' + Date.now().toString().slice(0, 10)
}

