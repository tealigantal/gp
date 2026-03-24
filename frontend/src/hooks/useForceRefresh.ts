import { useSyncExternalStore } from 'react'
import { getForceRefresh } from '../store/settings'

export function useForceRefreshFlag(): boolean {
  const subscribe = (cb: () => void) => {
    const handler = () => cb()
    window.addEventListener('gp_force_refresh_changed', handler)
    return () => window.removeEventListener('gp_force_refresh_changed', handler)
  }
  const getSnapshot = () => getForceRefresh()
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot)
}

