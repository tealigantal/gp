import { useEffect, useMemo, useRef, useState, useTransition } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ChatResponse, TranscriptEvent } from '../../shared/contracts'
import { getCurrentBook, getHealth, getSession, getSessions, postChat, readApiError } from '../../shared/api'
import { loadSessionId, newSessionId, saveSessionId } from '../../shared/session'

interface PendingTurn {
  sessionId: string
  userMessage: string
  assistant?: ChatResponse
}

interface SendMessageVariables {
  message: string
  sessionId: string
}

const HEALTH_POLL_MS = 30_000
const BOOK_POLL_MS = 15_000
const SESSION_STALE_MS = 30_000

export function useAdvisorWorkspace() {
  const queryClient = useQueryClient()
  const [sessionId, setSessionIdState] = useState(loadSessionId)
  const activeSessionIdRef = useRef(sessionId)
  const [composerValue, setComposerValue] = useState('')
  const [lastError, setLastError] = useState<string | null>(null)
  const [pendingTurn, setPendingTurn] = useState<PendingTurn | null>(null)
  const [latestResponse, setLatestResponse] = useState<ChatResponse | null>(null)
  const [isSessionSwitching, startSessionTransition] = useTransition()

  useEffect(() => {
    activeSessionIdRef.current = sessionId
  }, [sessionId])

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    staleTime: HEALTH_POLL_MS,
    refetchInterval: HEALTH_POLL_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const bookQuery = useQuery({
    queryKey: ['book', 'current'],
    queryFn: getCurrentBook,
    staleTime: BOOK_POLL_MS,
    refetchInterval: BOOK_POLL_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const sessionQuery = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    staleTime: SESSION_STALE_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const sessionsListQuery = useQuery({
    queryKey: ['sessions', 20],
    queryFn: () => getSessions(20),
    staleTime: SESSION_STALE_MS,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  const sendMessageMutation = useMutation({
    mutationFn: ({ message, sessionId }: SendMessageVariables) => postChat({ session_id: sessionId, message }),
    onMutate: async ({ message, sessionId }) => {
      setLastError(null)
      setPendingTurn({ sessionId, userMessage: message })
      setComposerValue('')
    },
    onSuccess: async (data, variables) => {
      if (variables.sessionId === activeSessionIdRef.current) {
        setLatestResponse(data)
        setPendingTurn((prev) => (prev && prev.sessionId === variables.sessionId ? { ...prev, assistant: data } : prev))
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['session', variables.sessionId] }),
        queryClient.invalidateQueries({ queryKey: ['book', 'current'] }),
        queryClient.invalidateQueries({ queryKey: ['sessions', 20] }),
      ])
    },
    onError: (error, variables) => {
      if (variables.sessionId === activeSessionIdRef.current) {
        setLastError(readApiError(error))
      }
      setPendingTurn((prev) => (prev?.sessionId === variables.sessionId ? null : prev))
    },
  })

  useEffect(() => {
    if (!pendingTurn?.assistant || pendingTurn.sessionId !== sessionId) return
    const turns = sessionQuery.data?.recent_turns || []
    const matched = turns.some((turn) => turn.role === 'assistant' && turn.content === pendingTurn.assistant?.reply)
    if (matched) setPendingTurn(null)
  }, [pendingTurn, sessionId, sessionQuery.data])

  const turns = useMemo<TranscriptEvent[]>(() => {
    const base = sessionQuery.data?.recent_turns || []
    if (!pendingTurn || pendingTurn.sessionId !== sessionId) return base
    const pending: TranscriptEvent[] = [
      {
        seq: Number.MAX_SAFE_INTEGER - 1,
        turn_id: 'pending',
        session_id: pendingTurn.sessionId,
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
        session_id: pendingTurn.sessionId,
        role: 'assistant',
        content: pendingTurn.assistant.reply,
        created_at: new Date().toISOString(),
        meta: {
          run_id: pendingTurn.assistant.run_id,
          symbols: pendingTurn.assistant.symbols,
          message: pendingTurn.assistant.message,
          right_panel: pendingTurn.assistant.right_panel,
        },
      })
    }
    return [...base, ...pending]
  }, [pendingTurn, sessionId, sessionQuery.data?.recent_turns])

  const setSessionId = (value: string) => {
    const next = value.trim() || newSessionId()
    saveSessionId(next)
    startSessionTransition(() => {
      setSessionIdState(next)
      setComposerValue('')
      setLastError(null)
      setPendingTurn(null)
      setLatestResponse(null)
    })
  }

  const resetSession = () => setSessionId(newSessionId())

  const submitMessage = async (message: string) => {
    const trimmed = message.trim()
    if (!trimmed) return
    await sendMessageMutation.mutateAsync({ message: trimmed, sessionId })
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
    isSessionSwitching,
    isInitialLoading:
      healthQuery.isLoading || bookQuery.isLoading || sessionQuery.isLoading,
  }
}
