import { render, screen } from '@testing-library/react'
import { Composer } from '../Composer'

function props(overrides: Partial<Parameters<typeof Composer>[0]> = {}) {
  return {
    value: '',
    onChange: () => undefined,
    onSubmit: () => undefined,
    ...overrides,
  }
}

it('keeps the composer enabled when a configured LLM can retry a rejected turn', () => {
  render(<Composer {...props({ llmReady: false, llmRetryable: true })} />)

  expect(screen.getByLabelText('Message composer')).toBeEnabled()
  expect(screen.getByText('上一次回答未通过证据校验，未展示也未保存。可直接重新发送问题，系统会再次调用真实 LLM。')).toBeInTheDocument()
})

it('disables the composer only when LLM configuration is unavailable', () => {
  render(<Composer {...props({ llmReady: false, llmRetryable: false })} />)

  expect(screen.getByLabelText('Message composer')).toBeDisabled()
  expect(screen.getByText('自然语言助手尚未配置，无法发起新的 LLM 请求。请检查后端配置。')).toBeInTheDocument()
})
