import { sync as apiSync, listEvents } from '../api/client'
import type { EventOut, SyncEventIn } from '../api/types'

type Listener = () => void

export type ConvState = {
  lastSeq: number
  events: EventOut[] // ordered by seq asc
}

function nowId() {
  return 'ev-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

export class SyncManager {
  private cursors: Record<string, number> = {}
  private outbox: SyncEventIn[] = []
  private conv: Record<string, ConvState> = {}
  private convMeta: Record<string, { id: string; title?: string; lastSeq: number; updatedAt?: string }> = {}
  private lastRead: Record<string, number> = {}
  private timer: any = null
  private syncing = false
  private pendingSync = false
  private aborter: AbortController | null = null
  // events polling state per conversation
  private evTimers: Record<string, any> = {}
  private evInFlight: Record<string, boolean> = {}
  private evAborters: Record<string, AbortController | null> = {}
  private listeners: Set<Listener> = new Set()
  private deviceId: string
  // optional getter to know current conversation for UI helpers
  currentConversationId?: () => string | null
  // sync scheduling
  private syncDebounceTimer: any = null
  private lastSyncAt = 0
  private syncCooldownMs = 1000
  private syncDebounceMs = 250
  private lastSyncReason: string = 'interval'

  constructor(deviceId?: string) {
    this.deviceId = deviceId || (localStorage.getItem('gp_device_id') || `dev-${crypto?.randomUUID?.() || Date.now()}`)
    localStorage.setItem('gp_device_id', this.deviceId)
    // hydrate cursors/outbox minimal
    try {
      const s = localStorage.getItem('gp_sync_cursors')
      this.cursors = s ? JSON.parse(s) : {}
    } catch { this.cursors = {} }
    try {
      const s2 = localStorage.getItem('gp_sync_outbox')
      this.outbox = s2 ? JSON.parse(s2) : []
    } catch { this.outbox = [] }
    try {
      const s3 = localStorage.getItem('gp_sync_last_read')
      this.lastRead = s3 ? JSON.parse(s3) : {}
    } catch { this.lastRead = {} }
  }

  subscribe(fn: Listener) {
    this.listeners.add(fn)
    return () => { this.listeners.delete(fn) }
  }
  private notify() { for (const fn of this.listeners) fn() }

  start(intervalActive = 30000, intervalBg = 60000) {
    if (this.timer) return
    const tick = async () => {
      try {
        this.requestSync('interval')
      } catch { /* ignore */ }
      const hidden = document.hidden
      const ms = hidden ? intervalBg : intervalActive
      this.timer = window.setTimeout(tick, ms)
    }
    // mark started before first tick to avoid StrictMode double-start
    this.timer = 1 as any
    tick()
  }
  stop() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null }
    if (this.aborter) { try { this.aborter.abort() } catch {} finally { this.aborter = null } }
    // stop all events pollers
    Object.keys(this.evTimers).forEach((cid) => this.stopEventsPolling(cid))
  }

  // --- local state maintenance helpers ---
  removeConversation(cid: string) {
    delete this.conv[cid]
    delete this.convMeta[cid]
    delete this.cursors[cid]
    delete this.lastRead[cid]
    try {
      localStorage.setItem('gp_sync_cursors', JSON.stringify(this.cursors))
      localStorage.setItem('gp_sync_last_read', JSON.stringify(this.lastRead))
    } catch { /* ignore */ }
    this.notify()
  }

  resetAll() {
    this.cursors = {}
    this.outbox = []
    this.conv = {}
    this.convMeta = {}
    this.lastRead = {}
    try {
      ;['gp_sync_cursors','gp_sync_outbox','gp_sync_last_read'].forEach((k)=>localStorage.removeItem(k))
    } catch { /* ignore */ }
    this.notify()
  }

  convState(cid: string): ConvState {
    if (!this.conv[cid]) this.conv[cid] = { lastSeq: this.cursors[cid] || 0, events: [] }
    return this.conv[cid]
  }

  setCursor(cid: string, seq: number) {
    if (!Number.isFinite(seq)) return
    if (!this.cursors[cid] || seq > this.cursors[cid]) {
      this.cursors[cid] = seq
      localStorage.setItem('gp_sync_cursors', JSON.stringify(this.cursors))
    }
  }

  async ensureLoaded(cid: string) {
    const st = this.convState(cid)
    const loadedLast = st.events.length > 0 ? st.events[st.events.length - 1].seq : 0
    const knownLast = Number(this.convMeta[cid]?.lastSeq || 0)
    const key = `gp:after:${cid}`
    // Case A: already loaded some, but not up to knownLast -> fetch increment
    if (st.events.length > 0) {
      if (knownLast > 0 && loadedLast < knownLast) {
        try {
          const data = await listEvents(cid, { after: loadedLast, limit: 200 } as any)
          if (Array.isArray(data) && data.length) this.mergeEvents(cid, data)
        } catch { /* ignore */ }
        return
      }
      // No knownLast yet (no sync meta), but we might still have more on server -> try one incremental pull
      try {
        const data = await listEvents(cid, { after: loadedLast, limit: 200 } as any)
        if (Array.isArray(data) && data.length) this.mergeEvents(cid, data)
      } catch { /* ignore */ }
      return
    }
    // Case B: empty memory -> hydrate a tail window around last known cursor
    let anchor = 0
    try { const saved = Number(localStorage.getItem(key) || '0'); if (Number.isFinite(saved) && saved > 0) anchor = saved } catch {}
    if (anchor <= 0 && knownLast > 0) anchor = knownLast
    let data: EventOut[] = []
    try {
      if (anchor > 0) {
        data = await listEvents(cid, { around: anchor, limit: 100 } as any)
      } else {
        data = await listEvents(cid, { after: 0, limit: 100 } as any)
      }
    } catch {
      try { data = await listEvents(cid, { after: 0, limit: 100 } as any) } catch { data = [] }
    }
    if (Array.isArray(data) && data.length) this.mergeEvents(cid, data)
    try { localStorage.setItem(key, String(this.convState(cid).lastSeq || 0)) } catch {}
    this.notify()
  }

  pushOutbox(ev: Omit<SyncEventIn, 'id'> & { id?: string }) {
    const e: SyncEventIn = { id: ev.id || nowId(), ...ev }
    this.outbox.push(e)
    localStorage.setItem('gp_sync_outbox', JSON.stringify(this.outbox))
    // 触发一次立即同步
    // 乐观更新：对 message.created 先写入本地视图，待服务端回写后按 id 覆盖 seq/数据
    try {
      if (e && e.conversation_id && e.type === 'message.created') {
        const cid = e.conversation_id
        const st = this.convState(cid)
        const pseudoSeq = (st.lastSeq || 0) + 1
        const shadow: EventOut = {
          id: e.id,
          conversation_id: cid,
          seq: pseudoSeq,
          type: 'message.created',
          actor_id: e.actor_id,
          created_at: new Date().toISOString(),
          data: e.data || {}
        }
        this.mergeEvents(cid, [shadow])
        this.notify()
      }
    } catch { /* ignore */ }
    this.flush().catch(() => undefined)
  }

  mergeEvents(cid: string, events: EventOut[]) {
    if (!events || events.length === 0) return
    const st = this.convState(cid)
    const map = new Map(st.events.map((e) => [e.id, e]))
    for (const e of events) {
      if (map.has(e.id)) {
        // 覆盖本地影子事件的 seq/数据等
        const ex = map.get(e.id)!
        ex.seq = e.seq
        ex.type = e.type
        ex.actor_id = e.actor_id
        ex.created_at = e.created_at
        ex.data = e.data
      } else {
        map.set(e.id, e)
        st.events.push(e)
      }
      if (e.seq > st.lastSeq) st.lastSeq = e.seq
      // handle edits/recall by type
      if (e.type === 'message.edited' || e.type === 'message.recalled') {
        // no-op in UI list for now; server materializes message table，前端仅展示 created 文本
      }
    }
    st.events.sort((a, b) => a.seq - b.seq)
    this.setCursor(cid, st.lastSeq)
    // persist last seq for incremental events polling
    try { localStorage.setItem(`gp:after:${cid}`, String(st.lastSeq || 0)) } catch {}
  }

  messages(cid: string) {
    const st = this.convState(cid)
    // derive text messages view from created events
    return st.events.filter((e) => e.type === 'message.created')
  }

  // Max merged sequence for a conversation (local view only)
  maxSeq(cid: string): number {
    const st = this.convState(cid)
    if (st.events.length > 0) return st.events[st.events.length - 1].seq || 0
    return 0
  }

  async flush(reason: string = 'manual') {
    // prevent concurrent syncs; coalesce fast callers
    if (this.syncing) { this.pendingSync = true; return }
    this.syncing = true
    this.pendingSync = false
    // Merge with persisted state to avoid losing events due to concurrent ticks or reloads
    // Merge with persisted state to avoid losing events due to concurrent ticks or reloads
    try {
      const persisted = localStorage.getItem('gp_sync_outbox')
      if (persisted) {
        const arr: any[] = JSON.parse(persisted)
        if (Array.isArray(arr)) {
          const map = new Map<string, SyncEventIn>()
          for (const e of this.outbox) { if (e && e.id) map.set(e.id, e) }
          for (const e of arr) { if (e && e.id && !map.has(e.id)) map.set(e.id, e as SyncEventIn) }
          this.outbox = Array.from(map.values())
        }
      }
    } catch { /* ignore parse errors */ }
    try {
      const persistedCursors = localStorage.getItem('gp_sync_cursors')
      if (persistedCursors) {
        const obj = JSON.parse(persistedCursors) || {}
        this.cursors = { ...obj, ...this.cursors }
      }
    } catch { /* ignore */ }
    const req = { device_id: this.deviceId, conv_cursors: this.cursors, outbox_events: this.outbox }
    // abort previous if any
    if (this.aborter) { try { this.aborter.abort() } catch {} }
    this.aborter = new AbortController()
    const resp = await apiSync(req, { signal: this.aborter.signal as any, headers: { 'X-Sync-Reason': reason } })
    // ack
    if (this.outbox.length) {
      const acks = resp.ack || {}
      this.outbox = this.outbox.filter((e) => !acks[e.id] || acks[e.id].startsWith('error:'))
      localStorage.setItem('gp_sync_outbox', JSON.stringify(this.outbox))
    }
    // deltas
    const deltas = resp.deltas || {}
    Object.keys(deltas).forEach((cid) => this.mergeEvents(cid, deltas[cid] || []))
    // conversations meta
    for (const it of (resp.conversations_delta || [])) {
      const cid = String(it.id)
      const lastSeq = Number(it.last_seq || 0)
      this.convMeta[cid] = { id: cid, title: it.title, lastSeq, updatedAt: it.updated_at }
      // IMPORTANT: do NOT advance local state cursor from server meta
      // st.lastSeq must only reflect merged event max seq to avoid skipping unseen events.
    }
    this.notify()
    this.lastSyncAt = Date.now()
    this.syncing = false
    // run one more time if needed (drop extra bursts)
    if (this.pendingSync) { this.pendingSync = false; try { this.requestSync('pending') } catch {} }
  }

  reportRead(cid: string, seq: number, actorId?: string) {
    if (!seq || seq <= 0) return
    this.pushOutbox({ conversation_id: cid, type: 'read.updated', data: { last_read_seq: seq }, actor_id: actorId })
    if (!this.lastRead[cid] || seq > this.lastRead[cid]) {
      this.lastRead[cid] = seq
      localStorage.setItem('gp_sync_last_read', JSON.stringify(this.lastRead))
    }
  }

  async jumpToSeq(cid: string, seq: number, limit = 60) {
    const data = await listEvents(cid, { around: seq, limit })
    this.mergeEvents(cid, data)
    this.notify()
  }

  getLastRead(cid: string) {
    return Number(this.lastRead[cid] || 0)
  }

  convList() {
    const items = Object.values(this.convMeta)
    return items
      .map((m) => ({
        id: m.id,
        title: m.title || m.id,
        lastSeq: m.lastSeq || 0,
        updatedAt: m.updatedAt,
        unread: Math.max((m.lastSeq || 0) - this.getLastRead(m.id), 0),
        preview: this.previewText(m.id)
      }))
      .sort((a, b) => (b.lastSeq - a.lastSeq))
  }

  previewText(cid: string) {
    const st = this.convState(cid)
    for (let i = st.events.length - 1; i >= 0; i--) {
      const e = st.events[i]
      if (e.type === 'message.created') return e.data?.content || ''
    }
    return ''
  }

  // Public: coalesced sync requests with debounce and cooldown
  requestSync(reason: string = 'manual') {
    this.lastSyncReason = reason || 'manual'
    if (this.syncDebounceTimer) clearTimeout(this.syncDebounceTimer)
    const fire = async () => {
      const now = Date.now()
      const since = now - this.lastSyncAt
      if (since < this.syncCooldownMs) {
        const wait = this.syncCooldownMs - since
        this.syncDebounceTimer = window.setTimeout(fire, wait)
        return
      }
      this.syncDebounceTimer = null
      try { await this.flush(this.lastSyncReason) } catch { /* ignore */ }
    }
    this.syncDebounceTimer = window.setTimeout(fire, this.syncDebounceMs)
  }

  // --- events incremental polling ---
  startEventsPolling(cid: string, intervalMs = 2500) {
    const doPoll = async () => {
      if (this.evInFlight[cid]) return
      this.evInFlight[cid] = true
      try {
        const key = `gp:after:${cid}`
        let after = 0
        try { const saved = Number(localStorage.getItem(key) || '0'); if (Number.isFinite(saved) && saved > 0) after = saved } catch {}
        if (after <= 0) {
          const st = this.convState(cid)
          const loadedLast = st.events.length > 0 ? st.events[st.events.length - 1].seq : 0
          after = loadedLast
        }
        const aborter = new AbortController()
        this.evAborters[cid] = aborter
        const data = await listEvents(cid, { after, limit: 100 } as any, { signal: aborter.signal as any })
        if (Array.isArray(data) && data.length) {
          this.mergeEvents(cid, data)
          this.notify()
        }
      } catch { /* ignore */ } finally {
        this.evInFlight[cid] = false
        const hidden = document.hidden
        const next = hidden ? intervalMs * 2 : intervalMs
        this.evTimers[cid] = window.setTimeout(doPoll, next)
      }
    }
    if (!this.evTimers[cid]) doPoll()
  }

  stopEventsPolling(cid: string) {
    if (this.evTimers[cid]) { clearTimeout(this.evTimers[cid]); delete this.evTimers[cid] }
    if (this.evAborters[cid]) { try { this.evAborters[cid]?.abort() } catch {} finally { delete this.evAborters[cid] } }
    delete this.evInFlight[cid]
  }
}

export const syncManager = new SyncManager()
