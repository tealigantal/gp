import { Alert, Card, Space, Tag, Typography } from 'antd'
import type { CanonicalMessage, MarketBook, TranscriptEvent } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'
import { MainConclusionCard } from './MainConclusionCard'
import { RecommendationMessageCard } from './RecommendationMessageCard'
import { FollowupTextMessage } from './FollowupTextMessage'
import { NoTradeMessageCard } from './NoTradeMessageCard'
import { ExitDecisionMessage } from './ExitDecisionMessage'
import { AssistantNarrativeBlock } from './AssistantNarrativeBlock'
import { SuggestedFollowups } from './SuggestedFollowups'
import { LiveCheckMessageCard } from './LiveCheckMessageCard'
import { RunChangeMessageCard } from './RunChangeMessageCard'

interface ChatThreadProps {
  turns: TranscriptEvent[]
  latestResponse: { message?: CanonicalMessage } | null
  error?: string | null
  sending: boolean
  book?: MarketBook
  onPrompt?: (text: string) => void
}

function renderFromCanonical(message: CanonicalMessage | undefined, onPrompt?: (t: string) => void) {
  if (!message) return null
  if (message.message_kind === 'recommend') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <RecommendationMessageCard picks={message.picks} onPrompt={onPrompt} />
        <AssistantNarrativeBlock text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(t) => onPrompt?.(t)} />
      </Space>
    )
  }
  if (message.message_kind === 'no_trade') return <NoTradeMessageCard reason={message.reason} text={message.narrative_text} />
  if (message.message_kind === 'exit') return <ExitDecisionMessage symbol={message.symbol || ''} text={message.narrative_text} />
  if (message.message_kind === 'live_check') return <LiveCheckMessageCard text={message.narrative_text} />
  if (message.message_kind === 'run_change') return <RunChangeMessageCard text={message.narrative_text} />
  if (message.message_kind === 'chat') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <FollowupTextMessage content={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(t) => onPrompt?.(t)} />
      </Space>
    )
  }
  // explain/compare/followup -> text
  return <FollowupTextMessage content={message.narrative_text} />
}

export function ChatThread({ turns, error, sending, book, onPrompt }: ChatThreadProps) {
  return (
    <div className="chat-thread">
      <MainConclusionCard book={book} />
      {error ? <Alert type="error" showIcon message="对话失败" description={error} /> : null}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {turns.map((turn) => {
          const isAssistant = turn.role === 'assistant'
          const meta = (turn.meta || {}) as Record<string, unknown>
          const symbols = Array.isArray(meta.symbols) ? (meta.symbols as string[]) : []
          const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
          const canonical = (meta['message'] as CanonicalMessage | undefined)

          const header = (
            <Space>
              <Tag color={isAssistant ? 'blue' : 'default'}>{isAssistant ? 'Assistant' : 'User'}</Tag>
              <Typography.Text type="secondary">{fmtTime(turn.created_at)}</Typography.Text>
              {runId ? <Tag>{runId}</Tag> : null}
              {symbols.map((symbol) => (
                <Tag key={symbol}>{symbol}</Tag>
              ))}
            </Space>
          )

          if (isAssistant) {
            return (
              <div key={`${turn.turn_id}-${turn.seq}`}>
                {header}
                {renderFromCanonical(canonical, onPrompt)}
              </div>
            )
          }
          return (
            <Card key={`${turn.turn_id}-${turn.seq}`} className="bubble bubble-user">
              <Space direction="vertical" size={8} style={{ width: '100%' }}>
                {header}
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>
                  {turn.content}
                </Typography.Paragraph>
              </Space>
            </Card>
          )
        })}
        {sending ? <Alert type="info" showIcon message="顾问正在基于当前账本生成判断中" /> : null}
      </Space>
    </div>
  )
}
