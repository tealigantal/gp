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
          message="LLM 未就绪，前端不会做兼容降级。请先配置后端 LLM。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <Space.Compact style={{ width: '100%' }}>
        <Input.TextArea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoSize={{ minRows: 2, maxRows: 5 }}
          placeholder="例如：第二只现在还能买吗；600183 的止损止盈怎么看；为什么这次没有上次那只。"
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
