import { Alert, Card, Space, Tag, Typography } from 'antd'
import type {
  CanonicalMessage,
  CanonicalRecommendMessage,
  RuntimeStatus,
  TranscriptEvent,
} from '../../../shared/contracts'
import { fmtTime } from '../../../shared/format'
import { AssistantNarrativeBlock } from './AssistantNarrativeBlock'
import { CompareMessageCard } from './CompareMessageCard'
import { ExitDecisionMessage } from './ExitDecisionMessage'
import { FollowupTextMessage } from './FollowupTextMessage'
import { LiveCheckMessageCard } from './LiveCheckMessageCard'
import { NoTradeMessageCard } from './NoTradeMessageCard'
import { PickDetailMessageCard } from './PickDetailMessageCard'
import { RecommendationMessageCard } from './RecommendationMessageCard'
import { RunChangeMessageCard } from './RunChangeMessageCard'
import { SuggestedFollowups } from './SuggestedFollowups'

interface ChatThreadProps {
  turns: TranscriptEvent[]
  error?: string | null
  sending: boolean
  runtime?: RuntimeStatus | null
  onPrompt?: (text: string) => void
}


function renderFromCanonical(
  message: CanonicalMessage | undefined,
  runtime?: RuntimeStatus | null,
  onPrompt?: (t: string) => void,
) {
  if (!message) return null
  if (message.message_kind === 'recommend') {
    const recommendMessage = message as CanonicalRecommendMessage
    const blocked = recommendMessage.run?.run_action === 'NO_TRADE' || (recommendMessage.picks || []).length === 0
    if (blocked) {
      return (
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
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
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <RecommendationMessageCard picks={recommendMessage.picks} run={recommendMessage.run} runtime={runtime} onPrompt={onPrompt} />
        <AssistantNarrativeBlock text={recommendMessage.narrative_text} />
        <SuggestedFollowups suggestions={recommendMessage.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'no_trade') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
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
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <PickDetailMessageCard detail={message.pick} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'single_stock_query') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <FollowupTextMessage content={message.narrative_text} label="单票分析" />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'live_entry_check') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <LiveCheckMessageCard view={message.live_check} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'compare') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <CompareMessageCard compare={message.compare} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'exit_decision') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <ExitDecisionMessage view={message.exit_decision} text={message.narrative_text} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'run_change') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <RunChangeMessageCard text={message.narrative_text} change={message.run_change} />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  if (message.message_kind === 'term_explain') {
    return (
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <FollowupTextMessage content={message.narrative_text} label="继续解释" />
        <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
      </Space>
    )
  }
  return (
    <Space direction="vertical" size={10} style={{ width: '100%' }}>
      <FollowupTextMessage content={message.narrative_text} label="助手回复" />
      <SuggestedFollowups suggestions={message.followup_suggestions} onPick={(text) => onPrompt?.(text)} />
    </Space>
  )
}

export function ChatThread({ turns, error, sending, runtime, onPrompt }: ChatThreadProps) {
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
          const canonical = meta.message as CanonicalMessage | undefined
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
                {renderFromCanonical(canonical, runtime, onPrompt)}
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
