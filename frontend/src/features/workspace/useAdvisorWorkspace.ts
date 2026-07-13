import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { AgentTurn, ChatResponse } from '../../shared/contracts'
import { getHealth, getSession, postChat, readApiError } from '../../shared/api'
import { loadSessionId, newSessionId, saveSessionId } from '../../shared/session'

const id = () => `turn_${crypto.randomUUID()}`

export function useAdvisorWorkspace() {
  const queryClient = useQueryClient()
  const [sessionId, setSessionId] = useState(loadSessionId)
  const [composerValue, setComposerValue] = useState('')
  const [lastError, setLastError] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const active = useRef(sessionId)
  useEffect(() => { active.current = sessionId }, [sessionId])

  const healthQuery = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000 })
  const sessionQuery = useQuery({
    queryKey: ['chat', sessionId], queryFn: () => getSession(sessionId), retry: false,
  })
  const send = useMutation({
    mutationFn: ({ message, turnId }: { message: string; turnId: string }) => postChat({
      session_id: sessionId, message, client_turn_id: turnId,
    }),
    onMutate: ({ message }) => { setLastError(null); setPending(message); setComposerValue('') },
    onSuccess: (data: ChatResponse) => {
      if (data.session_id !== active.current) return
      saveSessionId(data.session_id)
      setSessionId(data.session_id)
      queryClient.invalidateQueries({ queryKey: ['chat', data.session_id] })
    },
    onError: (error) => setLastError(readApiError(error)),
    onSettled: () => setPending(null),
  })
  const turns = useMemo<AgentTurn[]>(() => {
    const saved = sessionQuery.data?.turns || []
    return pending ? [...saved, { turn_id: 'pending', seq: Number.MAX_SAFE_INTEGER, role: 'user', content: pending, snapshot_id: '', payload: {}, created_at: new Date().toISOString() }] : saved
  }, [pending, sessionQuery.data])
  const resetSession = () => {
    const next = newSessionId(); setSessionId(next); setComposerValue(''); setLastError(null); setPending(null)
  }
  return {
    sessionId, resetSession, composerValue, setComposerValue, turns, health: healthQuery.data,
    isSending: send.isPending, lastError, isInitialLoading: healthQuery.isLoading,
    submitMessage: async (message: string) => { const trimmed = message.trim(); if (trimmed) await send.mutateAsync({ message: trimmed, turnId: id() }) },
  }
}
