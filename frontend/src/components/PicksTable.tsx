import { Table, Typography } from 'antd'

type Props = {
  picks?: any[]
  loading?: boolean
}

export default function PicksTable({ picks, loading }: Props) {
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
      window_B: actions?.window_B || '—'
    }
  })

  return (
    <Table
      loading={loading}
      dataSource={data}
      pagination={{ pageSize: 10 }}
      size="small"
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
  )
}

