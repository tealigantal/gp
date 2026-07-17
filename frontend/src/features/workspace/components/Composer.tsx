import { Alert, Button, Input, Space, Typography } from 'antd'

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
          message="自然语言助手当前不可用，请先检查后端配置，并确认 `/api/health` 返回 `llm_ready=true`。"
          style={{ marginBottom: 12 }}
        />
      ) : null}
      <div className="composer-headline">
        <Typography.Text className="section-kicker">Ask Naturally</Typography.Text>
        <Typography.Text className="section-subtitle">
          例如：今天给我 3 只；为什么第一只是它；这只现在还能买吗；为什么这次和上次不一样
        </Typography.Text>
      </div>
      <div className="composer-shell">
        <Space.Compact style={{ width: '100%' }}>
          <Input.TextArea
            value={value}
            onChange={(event) => onChange(event.target.value)}
            autoSize={{ minRows: 2, maxRows: 5 }}
            placeholder="直接说你的问题，不需要写指令格式。"
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
            发送问题
          </Button>
        </Space.Compact>
        <div className="composer-footer">
          <Typography.Text type="secondary">直接说问题本身，不需要先解释你要调用什么功能。</Typography.Text>
          <Typography.Text type="secondary">Enter 发送，Shift + Enter 换行</Typography.Text>
        </div>
      </div>
    </div>
  )
}
