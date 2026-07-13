import { Alert, Card, Space, Tag, Typography } from 'antd'
import type { AgentTurn } from '../../../shared/contracts'

export function ChatThread({ turns, error, sending }: { turns: AgentTurn[]; error?: string | null; sending: boolean }) {
  return <div className="chat-thread">
    {error ? <Alert type="error" showIcon message="这次回复没有完成" description={error} /> : null}
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      {turns.map((turn) => {
        const payload = turn.payload as { message?: { picks?: Array<{ symbol: string; name?: string; rank?: number; summary?: string; risk_flags?: string[] }> }; snapshot_id?: string; decision?: string }
        const picks = payload.message?.picks || []
        return <Card key={`${turn.turn_id}-${turn.seq}`} className={turn.role === 'assistant' ? 'bubble bubble-assistant' : 'bubble bubble-user'}>
          <Space direction="vertical" size={8} style={{ width: '100%' }}>
            <Space wrap><Tag color={turn.role === 'assistant' ? 'blue' : 'default'}>{turn.role === 'assistant' ? '助手' : '你'}</Tag>{turn.snapshot_id ? <Tag>{turn.snapshot_id}</Tag> : null}</Space>
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{turn.content}</Typography.Paragraph>
            {picks.map((pick) => <div key={pick.symbol}><Typography.Text strong>{pick.rank ? `#${pick.rank} ` : ''}{pick.symbol} {pick.name || ''}</Typography.Text><br /><Typography.Text type="secondary">{pick.summary || '请以快照中的入场和风控条件为准。'}</Typography.Text></div>)}
          </Space>
        </Card>
      })}
      {sending ? <Alert type="info" showIcon message="正在基于当前快照生成回复。" /> : null}
    </Space>
  </div>
}
