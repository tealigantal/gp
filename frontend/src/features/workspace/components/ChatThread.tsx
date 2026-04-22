import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'
import type { CanonicalMessage, MarketBook, TranscriptEvent } from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'
import { AssistantNarrativeBlock } from './AssistantNarrativeBlock'
import { ExitDecisionMessage } from './ExitDecisionMessage'
import { FollowupTextMessage } from './FollowupTextMessage'
import { LiveCheckMessageCard } from './LiveCheckMessageCard'
import { MainConclusionCard } from './MainConclusionCard'
import { NoTradeMessageCard } from './NoTradeMessageCard'
import { RecommendationMessageCard } from './RecommendationMessageCard'
import { RunChangeMessageCard } from './RunChangeMessageCard'
import { SuggestedFollowups } from './SuggestedFollowups'

interface ChatThreadProps {
  turns: TranscriptEvent[]
  error?: string | null
  sending: boolean
  book?: MarketBook
  onPrompt?: (text: string) => void
}

const starterPrompts = ['今天给我 3 只', '为什么第一只是它？', '600519 现在还能买吗？']

function renderFromCanonical(message: CanonicalMessage | undefined, onPrompt?: (t: string) => void) {
  if (!message) return null
  if (message.message_kind === 'recommend') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <RecommendationMessageCard picks={message.picks} onPrompt={onPrompt} />
        <AssistantNarrativeBlock text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
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
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  return <FollowupTextMessage content={message.narrative_text} />
}

export function ChatThread({ turns, error, sending, book, onPrompt }: ChatThreadProps) {
  return (
    <div className="chat-thread">
      <MainConclusionCard book={book} />
      {error ? (
        <div aria-live="polite">
          <Alert type="error" showIcon message="对话失败" description={error} />
        </div>
      ) : null}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {!turns.length && !sending ? (
          <Card className="empty-state-card">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="还没有对话。可以直接问盘中判断、推荐理由或策略说明。"
              />
              <SuggestedFollowups suggestions={starterPrompts} onPick={(text) => onPrompt?.(text)} />
            </Space>
          </Card>
        ) : null}
        {turns.map((turn) => {
          const isAssistant = turn.role === 'assistant'
          const meta = (turn.meta || {}) as Record<string, unknown>
          const symbols = Array.isArray(meta.symbols) ? (meta.symbols as string[]) : []
          const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
          const canonical = meta.message as CanonicalMessage | undefined

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
        {sending ? (
          <div aria-live="polite">
            <Alert type="info" showIcon message="顾问正在整理当前账本与上下文，请稍候。" />
          </div>
        ) : null}
      </Space>
    </div>
  )
}
