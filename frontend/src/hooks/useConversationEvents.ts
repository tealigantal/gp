import { useEffect, useRef } from 'react'
import { syncManager } from '../sync/SyncManager'

/**
 * Incrementally polls conversation events and merges into SyncManager.
 * - Persists last seq in localStorage key: gp:after:<sid>
 * - Poll interval ~2.5s (doubles when hidden)
 * - Dedup + ordering handled by SyncManager.mergeEvents
 */
export function useConversationEvents(sessionId?: string | null) {
  const sidRef = useRef<string | null | undefined>(sessionId)
  sidRef.current = sessionId

  useEffect(() => {
    const cid = sessionId
    if (!cid) return
    // ensure one-time load uses persisted cursor if any
    syncManager.ensureLoaded(cid).catch(() => undefined)
    // start polling
    syncManager.startEventsPolling(cid, 2500)
    return () => {
      // cleanup when session changes/unmounts
      syncManager.stopEventsPolling(cid)
    }
  }, [sessionId])
}

