import { Drawer, Table, Typography } from 'antd'
import { useState } from 'react'

type Props = {
  picks?: any[]
  loading?: boolean
}

export default function PicksTable({ picks, loading }: Props) {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState<any>(null)

  const data = (picks || []).map((it, idx) => {
    const bands = it?.trade_plan?.bands || it?.chip || {}
    const actions = it?.trade_plan?.actions || {}
    return {
      key: idx,
      symbol: it?.symbol,
      theme: it?.theme,
      strategy: it?.champion?.strategy || '—',
      S1: bands?.S1 ?? bands?.band_90_low ?? null,
      S2: bands?.S2 ?? bands?.avg_cost ?? null,
      R1: bands?.R1 ?? bands?.band_90_high ?? null,
      R2: bands?.R2 ?? (bands?.band_90_high ? bands?.band_90_high * 1.02 : null),
      window_A: actions?.window_A || '—',
      window_B: actions?.window_B || '—',
      raw: it
    }
  })

  return (
    <>
      <Table
        loading={loading}
        dataSource={data}
        pagination={{ pageSize: 10 }}
        size="small"
        onRow={(record) => ({
          onClick: () => {
            setCurrent(record.raw)
            setOpen(true)
          }
        })}
        columns={[
          { title: 'Symbol', dataIndex: 'symbol', key: 'symbol' },
          { title: 'Theme', dataIndex: 'theme', key: 'theme' },
          { title: 'Strategy', dataIndex: 'strategy', key: 'strategy' },
          { title: 'S1', dataIndex: 'S1', key: 'S1', render: (v) => (v != null ? <Typography.Text code>{Number(v).toFixed(2)}</Typography.Text> : '—') },
          { title: 'S2', dataIndex: 'S2', key: 'S2', render: (v) => (v != null ? <Typography.Text code>{Number(v).toFixed(2)}</Typography.Text> : '—') },
          { title: 'R1', dataIndex: 'R1', key: 'R1', render: (v) => (v != null ? <Typography.Text code>{Number(v).toFixed(2)}</Typography.Text> : '—') },
          { title: 'R2', dataIndex: 'R2', key: 'R2', render: (v) => (v != null ? <Typography.Text code>{Number(v).toFixed(2)}</Typography.Text> : '—') },
          { title: 'A窗动作', dataIndex: 'window_A', key: 'window_A' },
          { title: 'B窗动作', dataIndex: 'window_B', key: 'window_B' }
        ]}
      />
      <Drawer title={current?.symbol || '详情'} open={open} width={520} onClose={() => setOpen(false)}>
        {current && (
          <div>
            <p><strong>主题：</strong>{current?.theme || '—'}</p>
            <p><strong>策略：</strong>{current?.champion?.strategy || '—'}</p>
            <p><strong>买卖计划：</strong></p>
            <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(current?.trade_plan || {}, null, 2)}</pre>
            <p><strong>风控要点：</strong></p>
            <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(current?.risk || {}, null, 2)}</pre>
            <p><strong>失效条件：</strong></p>
            <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(current?.invalidation || {}, null, 2)}</pre>
          </div>
        )}
      </Drawer>
    </>
  )
}
