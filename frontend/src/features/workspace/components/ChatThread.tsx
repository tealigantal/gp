import { Alert, Card, Space, Tag, Typography } from 'antd'
import type { TranscriptEvent } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'
import { SuggestedFollowups } from './SuggestedFollowups'

interface ChatThreadProps {
  turns: TranscriptEvent[]
  error?: string | null
  sending: boolean
  onPrompt?: (text: string) => void
}

interface RenderableAssistantMessage {
  narrative_text: string
  followup_suggestions: string[]
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function renderableMessage(
  rawMessage: unknown,
  persistedContent: string,
): RenderableAssistantMessage | undefined {
  const raw = asRecord(rawMessage) || {}
  const narrative = typeof raw.narrative_text === 'string' && raw.narrative_text.trim()
    ? raw.narrative_text.trim()
    : persistedContent.trim()
  if (!narrative) return undefined

  const followupSuggestions = Array.isArray(raw.followup_suggestions)
    ? raw.followup_suggestions.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    : []
  return { narrative_text: narrative, followup_suggestions: followupSuggestions }
}

function renderAssistantReply(
  rawMessage: unknown,
  persistedContent: string,
  onPrompt?: (text: string) => void,
) {
  const message = renderableMessage(rawMessage, persistedContent)
  if (!message) {
    return (
      <Alert
        type="warning"
        showIcon
        message="该助手回合缺少可展示的正文"
        description="系统不会把空白内容当作有效回答；请刷新会话或重新提问。"
      />
    )
  }
  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <Typography.Paragraph className="assistant-message-text">{message.narrative_text}</Typography.Paragraph>
      <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
    </Space>
  )
}

export function ChatThread({ turns, error, sending, onPrompt }: ChatThreadProps) {
  return (
    <div className="chat-thread">
      {error ? (
        <div aria-live="polite">
          <Alert type="error" showIcon message="这次回复没有完成" description={error} />
        </div>
      ) : null}
      <Space direction="vertical" size={14} style={{ width: '100%' }}>
        {turns.map((turn) => {
          const isAssistant = turn.role === 'assistant'
          const meta = (turn.meta || {}) as Record<string, unknown>
          const symbols = Array.isArray(meta.symbols) ? (meta.symbols as string[]) : []
          const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
          const header = (
            <Space wrap className="message-meta">
              <Tag color={isAssistant ? 'blue' : 'default'}>{isAssistant ? '助手' : '你'}</Tag>
              <Typography.Text type="secondary">{fmtTime(turn.created_at)}</Typography.Text>
              {runId ? <Tag>{runId}</Tag> : null}
              {symbols.map((symbol) => (
                <Tag key={symbol}>{symbol}</Tag>
              ))}
            </Space>
          )
          if (isAssistant) {
            return (
              <div key={`${turn.turn_id}-${turn.seq}`} className="assistant-turn">
                {header}
                {renderAssistantReply(meta.message, turn.content, onPrompt)}
              </div>
            )
          }
          return (
            <Card key={`${turn.turn_id}-${turn.seq}`} className="bubble bubble-user">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {header}
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{turn.content}</Typography.Paragraph>
              </Space>
            </Card>
          )
        })}
        {sending ? (
          <div aria-live="polite">
            <Alert type="info" showIcon message="助手正在读取当前计划、上下文和风险边界，请稍候。" />
          </div>
        ) : null}
      </Space>
    </div>
  )
}
