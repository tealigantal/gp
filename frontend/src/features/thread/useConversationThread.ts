import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getThreadItems, postThreadRead } from '../../api/client'
import type { ThreadItem } from '../../api/contracts'

function dedupeMerge(arrA: ThreadItem[], arrB: ThreadItem[]): ThreadItem[] {
  const map = new Map<number, ThreadItem>()
  for (const it of [...arrA, ...arrB]) {
    map.set(it.seq, it)
  }
  return Array.from(map.values()).sort((a, b) => a.seq - b.seq)
}

export function useConversationThread(conversationId?: string | null, opts?: { anchor?: number; pageSize?: number; pollMs?: number }) {
  const cid = conversationId || undefined
  const pageSize = opts?.pageSize ?? 60
  const anchor = opts?.anchor
  const pollMs = opts?.pollMs ?? 4000

  const [items, setItems] = useState<ThreadItem[]>([])
  const [loading, setLoading] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const pollRef = useRef<number | null>(null)

  const minSeq = useMemo(() => (items.length ? items[0].seq : 0), [items])
  const maxSeq = useMemo(() => (items.length ? items[items.length - 1].seq : 0), [items])

  const loadInitial = useCallback(async () => {
    if (!cid) return
    setLoading(true)
    try {
      if (anchor && anchor > 0) {
        const back = await getThreadItems(cid, { anchor, direction: 'backward', limit: Math.ceil(pageSize / 2) })
        const fwd = await getThreadItems(cid, { anchor, direction: 'forward', limit: Math.ceil(pageSize / 2) })
        setItems(dedupeMerge(back, fwd))
      } else {
        const back = await getThreadItems(cid, { direction: 'backward', limit: pageSize })
        setItems(back)
      }
    } finally {
      setLoading(false)
      setInitialized(true)
    }
  }, [cid, anchor, pageSize])

  const loadOlder = useCallback(async () => {
    if (!cid) return
    const a = (minSeq ? minSeq - 1 : 0)
    const back = await getThreadItems(cid, { anchor: a, direction: 'backward', limit: pageSize })
    setItems((prev) => dedupeMerge(back, prev))
  }, [cid, minSeq, pageSize])

  const loadNewer = useCallback(async () => {
    if (!cid) return
    const fwd = await getThreadItems(cid, { anchor: maxSeq, direction: 'forward', limit: pageSize })
    setItems((prev) => dedupeMerge(prev, fwd))
  }, [cid, maxSeq, pageSize])

  // polling newer
  useEffect(() => {
    if (!cid) return
    // start only after initial load
    if (!initialized) return
    const id = window.setInterval(() => { loadNewer().catch(() => undefined) }, pollMs)
    pollRef.current = id as any
    return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
  }, [cid, initialized, pollMs, loadNewer])

  useEffect(() => { loadInitial().catch(() => undefined) }, [loadInitial])

  const reportRead = useCallback(async () => {
    if (!cid || !maxSeq) return
    try { await postThreadRead(cid, { last_read_seq: maxSeq }) } catch {}
  }, [cid, maxSeq])

  return { items, loading, loadOlder, loadNewer, reportRead, minSeq, maxSeq }
}

