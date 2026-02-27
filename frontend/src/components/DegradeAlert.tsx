import { Alert } from 'antd'

const reasonMap: Record<string, string> = {
  SNAPSHOT_MISSING: '当日快照不可用',
  SNAPSHOT_FALLBACK: '快照回退',
  THEMES_EMPTY: '主题为空',
  BARS_TOO_SHORT: '历史样本长度不足',
  INDICATOR_PARTIAL: '指标计算部分失败',
  UNIVERSE_TOO_SMALL: '股票池过小',
  CANDIDATE_TOO_SMALL: '候选数量不足',
  STRATEGY_EVAL_FAILED: '策略评估失败',
  MAINLINE_MISSING: '主线缺失',
}

export default function DegradeAlert({ reasons }: { reasons: Array<{ reason_code: string; detail?: any }> }) {
  if (!reasons || reasons.length === 0) return null
  return (
    <Alert
      type="warning"
      showIcon
      message={<span>降级（debug.degraded = true）</span>}
      description={(
        <div>
          <div>原因：</div>
          <ul style={{ marginTop: 8 }}>
            {reasons.map((r, idx) => (
              <li key={idx}>
                <code>{r.reason_code}</code>
                {reasonMap[r.reason_code] ? `（${reasonMap[r.reason_code]}）` : ''}
                {r.detail ? (
                  <>
                    {' '}<small>{Object.entries(r.detail).map(([k,v]) => `${k}=${String(v)}`).join(' ')}</small>
                  </>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      )}
    />
  )
}
