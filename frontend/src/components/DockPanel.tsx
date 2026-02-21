import { Card, Drawer } from 'antd'
import KlineChart from './KlineChart'

export default function DockPanel({ open, symbol, onClose }: { open: boolean; symbol?: string | null; onClose: () => void }) {
  return (
    <Drawer title={symbol ? `K线 · ${symbol}` : 'K线'} placement="right" width={420} onClose={onClose} open={open} destroyOnClose>
      {symbol ? (
        <Card size="small">
          <KlineChart symbol={symbol} />
        </Card>
      ) : null}
    </Drawer>
  )
}

