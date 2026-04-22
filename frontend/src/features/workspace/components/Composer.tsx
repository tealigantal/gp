import { Alert, Button, Input, Space } from 'antd'

interface ComposerProps {
  value: string
  onChange: (value: string) => void
  onSubmit: () => void
  disabled?: boolean
  llmReady?: boolean
}

export function Composer({ value, onChange, onSubmit, disabled, llmReady }: ComposerProps) {
  return (
    <div className="composer-wrap">
      {!llmReady ? (
        <Alert
          type="warning"
          showIcon
          message="LLM 当前不可用，请检查后端配置并确认 `/api/health` 返回 `llm_ready=true`。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 2, maxRows: 5 }}
          placeholder="例如：今天给我 3 只；为什么第一只是它；600519 现在还能买吗；S1-S14 都是什么。"
          aria-label="Message composer"
          name="message"
          autoComplete="off"
          onPressEnter={(event) => {
            if (!event.shiftKey) {
              event.preventDefault()
              onSubmit()
            }
          }}
          disabled={disabled || !llmReady}
        />
        <Button type="primary" onClick={onSubmit} loading={disabled} disabled={!llmReady}>
          发送
        </Button>
      </Space.Compact>
    </div>
  )
}
