import { Alert, Card, Empty, Space, Tag, Typography } from 'antd'
import type {
  CanonicalMessage,
  CanonicalRecommendMessage,
  MarketBook,
  TranscriptEvent,
} from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'
import { AssistantNarrativeBlock } from './AssistantNarrativeBlock'
import { CompareMessageCard } from './CompareMessageCard'
import { ExitDecisionMessage } from './ExitDecisionMessage'
import { FollowupTextMessage } from './FollowupTextMessage'
import { LiveCheckMessageCard } from './LiveCheckMessageCard'
import { MainConclusionCard } from './MainConclusionCard'
import { NoTradeMessageCard } from './NoTradeMessageCard'
import { PickDetailMessageCard } from './PickDetailMessageCard'
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

const starterPrompts = ['今天给我 3 只', '第二个还能冲吗', '为什么这次和上次不一样']

function renderFromCanonical(message: CanonicalMessage | undefined, onPrompt?: (t: string) => void) {
  if (!message) return null
  if (message.message_kind === 'recommend') {
    const recommendMessage = message as CanonicalRecommendMessage
    const blocked = recommendMessage.run?.run_action === 'NO_TRADE' || (recommendMessage.picks || []).length === 0
    if (blocked) {
      return (
        <Space direction="vertical" size={8} style={{ width: '100%' }}>
          <NoTradeMessageCard
            reason={recommendMessage.run?.status_reason || recommendMessage.narrative_text}
            text={recommendMessage.narrative_text}
            noTradeReasons={recommendMessage.run?.no_trade_reasons || []}
            recoveryConditions={recommendMessage.run?.recovery_conditions || []}
            marketSummary={recommendMessage.run?.status_reason || recommendMessage.narrative_text}
          />
          <SuggestedFollowups suggestions={recommendMessage.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
        </Space>
      )
    }
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <RecommendationMessageCard picks={recommendMessage.picks} run={recommendMessage.run} onPrompt={onPrompt} />
        <AssistantNarrativeBlock text={recommendMessage.narrative_text} />
        <SuggestedFollowups suggestions={recommendMessage.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'no_trade') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <NoTradeMessageCard
          reason={message.reason}
          text={message.narrative_text}
          noTradeReasons={message.no_trade_reasons}
          recoveryConditions={message.recovery_conditions}
          marketSummary={message.market_summary}
        />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'pick_detail') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <PickDetailMessageCard detail={message.pick} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'live_entry_check') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <LiveCheckMessageCard view={message.live_check} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'compare') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <CompareMessageCard compare={message.compare} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'exit_decision') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <ExitDecisionMessage view={message.exit_decision} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'run_change') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <RunChangeMessageCard text={message.narrative_text} change={message.run_change} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'term_explain') {
    return (
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <FollowupTextMessage content={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  return (
    <Space direction="vertical" size={8} style={{ width: '100%' }}>
      <FollowupTextMessage content={message.narrative_text} />
      <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
    </Space>
  )
}

export function ChatThread({ turns, error, sending, book, onPrompt }: ChatThreadProps) {
  const latestTurn = turns.length > 0 ? turns[turns.length - 1] : undefined
  const latestMessage = (latestTurn?.meta as Record<string, unknown> | undefined)?.message as CanonicalMessage | undefined

  return (
    <div className="chat-thread">
      <MainConclusionCard book={book} latestMessage={latestMessage} />
      {error ? (
        <div aria-live="polite">
          <Alert type="error" showIcon message="对话失败" description={error} />
        </div>
      ) : null}
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {!turns.length && !sending ? (
          <Card className="empty-state-card">
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有对话。可以直接问今天的机会、盘中能不能进，或者某只票的风控。" />
              <SuggestedFollowups suggestions={starterPrompts} onPick={(text) => onPrompt?.(text)} />
            </Space>
          </Card>
        ) : null}
        {turns.map((turn) => {
          const isAssistant = turn.role === 'assistant'
          const meta = (turn.meta || {}) as Record<string, unknown>
          const symbols = Array.isArray(meta.symbols) ? (meta.symbols as string[]) : []
          const canonical = meta.message as CanonicalMessage | undefined
          const runId = typeof meta.run_id === 'string' ? meta.run_id : undefined
          const header = (
            <Space wrap>
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
                <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}>{turn.content}</Typography.Paragraph>
              </Space>
            </Card>
          )
        })}
        {sending ? (
          <div aria-live="polite">
            <Alert type="info" showIcon message="顾问正在读取当前 run、5 分钟执行状态和上下文，请稍候。" />
          </div>
        ) : null}
      </Space>
    </div>
  )
}
