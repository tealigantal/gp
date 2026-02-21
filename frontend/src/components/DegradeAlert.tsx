import { Alert } from 'antd'

const reasonMap: Record<string, string> = {
  snapshot_unavailable: '当日快照不可用',
  insufficient_history: '历史样本长度不足',
  data_unavailable: '数据源不可用',
  provider_error: '数据提供方错误',
  candidates_too_few: '候选数量不足',
  universe_too_small: '股票池过小',
  market_closed: '非交易时段',
}

export default function DegradeAlert({ reasons }: { reasons: Array<{ reason_code: string; detail?: any }> }) {
  if (!reasons || reasons.length === 0) return null
  return (
    <Alert
      type="warning"
      showIcon
      message={<span>降级运行（debug.degraded = true）</span>}
      description={(
        <div>
          <div>原因：</div>
          <ul style={{ marginTop: 8 }}>
            {reasons.map((r, idx) => (
              <li key={idx}>
                <code>{r.reason_code}</code>
                {reasonMap[r.reason_code] ? `（${reasonMap[r.reason_code]}）` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    />
  )
}

