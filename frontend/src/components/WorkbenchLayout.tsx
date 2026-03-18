import React, { useEffect, useRef, useState } from 'react'
import { Button, Drawer } from 'antd'
import { usePreventHistorySwipe } from '../hooks/usePreventHistorySwipe'

export default function WorkbenchLayout({
  left,
  center,
  right,
}: {
  left?: React.ReactNode
  center: React.ReactNode
  right?: React.ReactNode
}) {
  const [narrow, setNarrow] = useState<boolean>(() => (typeof window !== 'undefined' ? window.innerWidth <= 992 : false))
  const [openLeft, setOpenLeft] = useState(false)
  const [openRight, setOpenRight] = useState(false)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth <= 992)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const rootRef = useRef<HTMLDivElement | null>(null)
  usePreventHistorySwipe(rootRef)

  if (narrow) {
    return (
      <div ref={rootRef} className="workbench-shell">
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
          {left && <Button onClick={() => setOpenLeft(true)}>会话</Button>}
          {right && <Button onClick={() => setOpenRight(true)}>信息面板</Button>}
        </div>
        <div className="workbench-pane">{center}</div>
        <Drawer title="会话" placement="left" width={320} onClose={() => setOpenLeft(false)} open={openLeft} destroyOnClose={false}>
          <div className="workbench-pane">{left}</div>
        </Drawer>
        <Drawer title="信息面板" placement="right" width={380} onClose={() => setOpenRight(false)} open={openRight} destroyOnClose={false}>
          <div className="workbench-pane">{right}</div>
        </Drawer>
      </div>
    )
  }

  return (
    <div ref={rootRef} className="workbench-shell" style={{ display: 'grid', gridTemplateColumns: `${left ? '280px ' : ''}1fr ${right ? '380px' : ''}`, gap: 16, alignItems: 'stretch', height: '100%', minHeight: 0 }}>
      {left && (
        <div className="workbench-pane" style={{ minWidth: 0, overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {left}
        </div>
      )}
      <div className="workbench-pane" style={{ minWidth: 0, overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {center}
      </div>
      {right && (
        <div className="workbench-pane" style={{ minWidth: 0, overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          {right}
        </div>
      )}
    </div>
  )
}
