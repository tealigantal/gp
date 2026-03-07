import React, { useEffect, useState } from 'react'
import { Button, Drawer } from 'antd'

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

  if (narrow) {
    return (
      <div>
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between' }}>
          {left && <Button onClick={() => setOpenLeft(true)}>会话</Button>}
          {right && <Button onClick={() => setOpenRight(true)}>信息面板</Button>}
        </div>
        <div>{center}</div>
        <Drawer title="会话" placement="left" width={320} onClose={() => setOpenLeft(false)} open={openLeft} destroyOnClose>
          {left}
        </Drawer>
        <Drawer title="信息面板" placement="right" width={380} onClose={() => setOpenRight(false)} open={openRight} destroyOnClose>
          {right}
        </Drawer>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: `${left ? '280px ' : ''}1fr ${right ? '380px' : ''}`, gap: 16, alignItems: 'stretch' }}>
      {left && <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>{left}</div>}
      <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>{center}</div>
      {right && <div style={{ minWidth: 0, overflow: 'hidden', height: '100%' }}>{right}</div>}
    </div>
  )
}
