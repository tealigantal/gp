import { useEffect } from 'react'

// Prevent back/forward navigation triggered by horizontal swipe/scroll gestures
// Attach only to a specific container (e.g., .workbench-shell), not document
export function usePreventHistorySwipe(ref: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = ref.current
    if (!root) return

    let touchStartX = 0
    let touchStartY = 0

    const onWheel = (e: WheelEvent) => {
      // Only consider clear horizontal gestures
      const dx = Math.abs(e.deltaX)
      const dy = Math.abs(e.deltaY)
      if (dx > dy && dx > 8) {
        // Prevent browser back/forward on horizontal swipe
        e.preventDefault()
      }
    }

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      touchStartX = e.touches[0].clientX
      touchStartY = e.touches[0].clientY
    }

    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length !== 1) return
      const dx = e.touches[0].clientX - touchStartX
      const dy = e.touches[0].clientY - touchStartY
      // Only prevent on obvious horizontal pans so vertical scroll remains natural
      if (Math.abs(dx) > Math.abs(dy) * 1.2 && Math.abs(dx) > 10) {
        e.preventDefault()
      }
    }

    root.addEventListener('wheel', onWheel, { passive: false })
    root.addEventListener('touchstart', onTouchStart, { passive: true })
    root.addEventListener('touchmove', onTouchMove, { passive: false })
    return () => {
      root.removeEventListener('wheel', onWheel as any)
      root.removeEventListener('touchstart', onTouchStart as any)
      root.removeEventListener('touchmove', onTouchMove as any)
    }
  }, [ref])
}

