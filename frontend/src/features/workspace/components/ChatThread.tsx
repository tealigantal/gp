import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'
import type { ChatResponse, TranscriptEvent } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'

interface ChatThreadProps {
  turns: TranscriptEvent[]
  latestResponse: ChatResponse | null
  error?: string | null
  sending: boolean
}

export function ChatThread({ turns, latestResponse, error, sending }: ChatThreadProps) {
  return (
    <div className="chat-thread">
      {error ? <Alert type="error" showIcon message="对话失败" description={error} /> : null}
      {latestResponse?.planner_trace ? (
        <Card size="small" title="最近一轮结构化理解" extra={<Tag>{latestResponse.run_id || 'no run'}</Tag>}>
          <pre className="json-block">{JSON.stringify(latestResponse.planner_trace, null, 2)}</pre>
        </Card>
      ) : null}
      {turns.length === 0 ? (
        <Card>
          <Empty description="先聊一句，比如：给我今天 3 只。" />
        </Card>
      ) : null}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {turns.map((turn) => {
          const isAssistant = turn.role === 'assistant'
          const meta = (turn.meta || {}) as Record<string, unknown>
          const symbols = Array.isArray(meta.symbols) ? (meta.symbols as string[]) : []
          const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
          return (
            <Card key={`${turn.turn_id}-${turn.seq}`} className={isAssistant ? 'bubble bubble-assistant' : 'bubble bubble-user'}>
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                <Space>
                  <Tag color={isAssistant ? 'blue' : 'default'}>{isAssistant ? 'Assistant' : 'User'}</Tag>
                  <Typography.Text type="secondary">{fmtTime(turn.created_at)}</Typography.Text>
                  {runId ? <Tag>{runId}</Tag> : null}
                  {symbols.map((symbol) => <Tag key={symbol}>{symbol}</Tag>)}
                </Space>
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                  {turn.content}
                </Typography.Paragraph>
              </Space>
            </Card>
          )
        })}
        {sending ? <Alert type="info" showIcon message="顾问正在基于当前账本生成判断…" /> : null}
      </Space>
    </div>
  )
}
