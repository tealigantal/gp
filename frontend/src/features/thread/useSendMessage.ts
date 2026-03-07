import { useMutation } from '@tanstack/react-query'
import { chat } from '../../api/client'
import type { ChatReq, ChatResp } from '../../api/types'

export function useSendMessage() {
  return useMutation<ChatResp, Error, ChatReq>({
    mutationFn: async (body: ChatReq) => chat(body),
  })
}

