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
  private listeners: Set<Listener> = new Set()
  private deviceId: string

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
    return () => this.listeners.delete(fn)
  }
  private notify() { for (const fn of this.listeners) fn() }

  start(intervalActive = 3000, intervalBg = 9000) {
    const tick = async () => {
      try {
        await this.flush()
      } catch { /* ignore */ }
      const hidden = document.hidden
      const ms = hidden ? intervalBg : intervalActive
      this.timer = window.setTimeout(tick, ms)
    }
    if (!this.timer) tick()
  }
  stop() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null }
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
    if (st.events.length === 0) {
      const data = await listEvents(cid, { after: 0, limit: 100 })
      this.mergeEvents(cid, data)
      this.notify()
    }
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

  private mergeEvents(cid: string, events: EventOut[]) {
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
  }

  messages(cid: string) {
    const st = this.convState(cid)
    // derive text messages view from created events
    return st.events.filter((e) => e.type === 'message.created')
  }

  async flush() {
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
    const resp = await apiSync(req)
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
      // keep state in sync
      const st = this.convState(cid)
      if (lastSeq > st.lastSeq) st.lastSeq = lastSeq
    }
    this.notify()
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
}

export const syncManager = new SyncManager()
