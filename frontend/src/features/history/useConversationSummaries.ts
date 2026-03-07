import { useQuery } from '@tanstack/react-query'
import { getConversationSummaries } from '../../api/client'
import { asConversationSummary } from '../../api/adapters'
import type { ConversationSummary } from '../../api/contracts'

export function useConversationSummaries() {
  return useQuery<ConversationSummary[]>({
    queryKey: ['conversation-summaries'],
    queryFn: async () => {
      const data = await getConversationSummaries()
      return (data || []).map(asConversationSummary)
    },
    refetchOnWindowFocus: false,
  })
}

