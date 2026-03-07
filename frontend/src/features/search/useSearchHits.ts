import { useMutation } from '@tanstack/react-query'
import { searchHits } from '../../api/client'
import { asSearchHits } from '../../api/adapters'
import type { SearchHit } from '../../api/contracts'

export function useSearchHits() {
  return useMutation<SearchHit[], Error, { q: string; conversation_id?: string; limit?: number }>({
    mutationFn: async (params) => {
      const data = await searchHits(params)
      return asSearchHits(data)
    },
  })
}
