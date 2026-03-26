import { Button, Card, Space, Typography } from 'antd'
import type { AdviceRun, MarketBook } from '../../../shared/contracts'

interface QuickPromptsProps {
  book?: MarketBook
  run?: AdviceRun
  onPrompt: (message: string) => void
}

export function QuickPrompts({ book, run, onPrompt }: QuickPromptsProps) {
  const first = run?.picks?.[0] || book?.board?.[0]
  const second = run?.picks?.[1] || book?.board?.[1]

  return (
    <Card size="small" title="快捷追问">
      <Space direction="vertical" size={8} style={{ width: '100%' }}>
        <Space wrap>
          <Button onClick={() => onPrompt('给我今天 3 只')}>给我今天 3 只</Button>
          <Button onClick={() => onPrompt('今天为什么空仓')}>为什么空仓</Button>
          <Button onClick={() => onPrompt('用当前最新账本再看一眼')}>按最新账本再看一眼</Button>
        </Space>
        <Typography.Text type="secondary">
          这些操作都只走新的 Concern → Evidence → Judgment 主链，不会再触发旧前端兼容逻辑。
        </Typography.Text>
        <Space wrap>
          {first ? <Button onClick={() => onPrompt(`看看 ${first.symbol} 现在还能买吗`)}>跟踪 {first.symbol}</Button> : null}
          {second ? <Button onClick={() => onPrompt(`比较 ${first?.symbol} 和 ${second.symbol}`)}>比较前两只</Button> : null}
          {first ? <Button onClick={() => onPrompt(`现在 ${first.symbol} 该不该卖`)}>卖出判断</Button> : null}
        </Space>
      </Space>
    </Card>
  )
}
