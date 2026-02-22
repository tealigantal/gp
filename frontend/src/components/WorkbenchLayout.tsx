import React, { useEffect, useState } from 'react'
import { Button, Drawer } from 'antd'

export default function WorkbenchLayout({
  left,
  right
}: {
  left: React.ReactNode
  right: React.ReactNode
}) {
  const [narrow, setNarrow] = useState<boolean>(() => typeof window !== 'undefined' ? window.innerWidth <= 992 : false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth <= 992)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (narrow) {
    return (
      <div>
        <div style={{ marginBottom: 12, textAlign: 'right' }}>
          <Button onClick={() => setOpen(true)}>信息面板</Button>
        </div>
        <div>{left}</div>
        <Drawer title="信息面板" placement="right" width={360} onClose={() => setOpen(false)} open={open} destroyOnClose>
          {right}
        </Drawer>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(640px, 1fr) 380px', gap: 20 }}>
      <div>{left}</div>
      <div style={{ position: 'sticky', top: 12, alignSelf: 'start' }}>{right}</div>
    </div>
  )
}
