import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ChatResponse, TranscriptEvent } from '../../shared/contracts'
import { getCurrentBook, getHealth, getSession, getSessions, postChat, readApiError } from '../../shared/api'
import { loadSessionId, newSessionId, saveSessionId } from '../../shared/session'

interface PendingTurn {
  userMessage: string
  assistant?: ChatResponse
}

export function useAdvisorWorkspace() {
  const queryClient = useQueryClient()
  const [sessionId, setSessionIdState] = useState(loadSessionId)
  const [composerValue, setComposerValue] = useState('')
  const [lastError, setLastError] = useState<string | null>(null)
  const [pendingTurn, setPendingTurn] = useState<PendingTurn | null>(null)
  const [latestResponse, setLatestResponse] = useState<ChatResponse | null>(null)

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 15000,
  })

  const bookQuery = useQuery({
    queryKey: ['book', 'current'],
    queryFn: getCurrentBook,
    refetchInterval: 15000,
  })

  const sessionQuery = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    refetchInterval: 10000,
  })

  const sessionsListQuery = useQuery({
    queryKey: ['sessions', 20],
    queryFn: () => getSessions(20),
    refetchInterval: 20000,
  })

  const sendMessageMutation = useMutation({
    mutationFn: (message: string) => postChat({ session_id: sessionId, message }),
    onMutate: async (message) => {
      setLastError(null)
      setPendingTurn({ userMessage: message })
      setComposerValue('')
    },
    onSuccess: async (data) => {
      setLatestResponse(data)
      setPendingTurn((prev) => (prev ? { ...prev, assistant: data } : null))
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['book', 'current'] }),
        queryClient.invalidateQueries({ queryKey: ['sessions', 20] }),
      ])
    },
    onError: (error) => {
      setLastError(readApiError(error))
      setPendingTurn(null)
    },
  })

  useEffect(() => {
    if (!pendingTurn?.assistant) return
    const turns = sessionQuery.data?.recent_turns || []
    const matched = turns.some((turn) => turn.role === 'assistant' && turn.content === pendingTurn.assistant?.reply)
    if (matched) setPendingTurn(null)
  }, [pendingTurn, sessionQuery.data])

  const turns = useMemo<TranscriptEvent[]>(() => {
    const base = sessionQuery.data?.recent_turns || []
    if (!pendingTurn) return base
    const pending: TranscriptEvent[] = [
      {
        seq: Number.MAX_SAFE_INTEGER - 1,
        turn_id: 'pending',
        session_id: sessionId,
        role: 'user',
        content: pendingTurn.userMessage,
        created_at: new Date().toISOString(),
        meta: {},
      },
    ]
    if (pendingTurn.assistant) {
      pending.push({
        seq: Number.MAX_SAFE_INTEGER,
        turn_id: 'pending',
        session_id: sessionId,
        role: 'assistant',
        content: pendingTurn.assistant.reply,
        created_at: new Date().toISOString(),
        meta: {
          run_id: pendingTurn.assistant.run_id,
          symbols: pendingTurn.assistant.symbols,
          message: pendingTurn.assistant.message,
          right_panel: pendingTurn.assistant.right_panel,
          planner_trace: pendingTurn.assistant.planner_trace,
        },
      })
    }
    return [...base, ...pending]
  }, [pendingTurn, sessionId, sessionQuery.data?.recent_turns])

  const setSessionId = (value: string) => {
    const next = value.trim() || newSessionId()
    saveSessionId(next)
    setSessionIdState(next)
    setComposerValue('')
    setLastError(null)
    setPendingTurn(null)
    setLatestResponse(null)
  }

  const resetSession = () => setSessionId(newSessionId())

  const submitMessage = async (message: string) => {
    const trimmed = message.trim()
    if (!trimmed) return
    await sendMessageMutation.mutateAsync(trimmed)
  }

  return {
    sessionId,
    setSessionId,
    resetSession,
    composerValue,
    setComposerValue,
    submitMessage,
    isSending: sendMessageMutation.isPending,
    lastError,
    latestResponse,
    turns,
    health: healthQuery.data,
    book: bookQuery.data?.book,
    session: sessionQuery.data,
    sessions: sessionsListQuery.data || [],
    isInitialLoading:
      healthQuery.isLoading || bookQuery.isLoading || sessionQuery.isLoading,
  }
}
