import { Button, Card, Empty, Space, Tag, Typography } from 'antd'
import type { AdviceRun, BoardEntry } from '../../../shared/contracts'
import { compactJson, fmtNum, tagColorByExecution } from '../../../shared/format'

interface RunPanelProps {
  run?: AdviceRun
  onPrompt: (message: string) => void
}

function PickCard({ entry, onPrompt }: { entry: BoardEntry; onPrompt: (message: string) => void }) {
  return (
    <Card size="small" title={`${entry.rank}. ${entry.symbol}${entry.name ? ` · ${entry.name}` : ''}`} extra={<Tag color={tagColorByExecution(entry.execution_state)}>{entry.execution_state}</Tag>}>
      <Space direction="vertical" size={10} style={{ width: '100%' }}>
        <Typography.Paragraph style={{ marginBottom: 0 }}>{entry.pick.thesis || entry.summary}</Typography.Paragraph>
        <Space wrap>
          {entry.pick.style_label ? <Tag>{entry.pick.style_label}</Tag> : null}
          {entry.pick.strategy_id ? <Tag>{entry.pick.strategy_id}</Tag> : null}
          <Tag color={entry.can_open ? 'green' : 'default'}>{entry.can_open ? '可执行' : '观察'}</Tag>
          {entry.pick.risk_flags.map((flag) => <Tag key={flag} color="orange">{flag}</Tag>)}
        </Space>
        <Typography.Text strong>计划</Typography.Text>
        <pre className="json-block">{compactJson({
          entry: entry.pick.entry_plan,
          stop: entry.pick.stop_plan,
          take: entry.pick.take_profit_plan,
          scores: entry.pick.scores,
        })}</pre>
        <Space wrap>
          <Button size="small" onClick={() => onPrompt(`看看 ${entry.symbol} 现在还能买吗`)}>现在还能买吗</Button>
          <Button size="small" onClick={() => onPrompt(`为什么 ${entry.symbol} 是第 ${entry.rank} 只`)}>为什么排这里</Button>
          <Button size="small" onClick={() => onPrompt(`现在 ${entry.symbol} 该不该卖`)}>卖出判断</Button>
        </Space>
      </Space>
    </Card>
  )
}

export function RunPanel({ run, onPrompt }: RunPanelProps) {
  if (!run?.run_id) {
    return <Card><Empty description="当前会话还没有发布 Advice Run。" /></Card>
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title="Active Advice Run" extra={<Tag>{run.run_id}</Tag>}>
        <Space wrap>
          <Tag color={run.tradeable ? 'green' : 'orange'}>{run.tradeable ? 'tradeable' : 'observe'}</Tag>
          <Tag>{run.trading_day}</Tag>
          <Tag>{run.book_version}</Tag>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          {run.reason || '该快照是顾问对外承诺的冻结切片，用于后续追问与变化解释。'}
        </Typography.Paragraph>
      </Card>
      {run.picks.map((entry) => <PickCard key={entry.symbol} entry={entry} onPrompt={onPrompt} />)}
    </Space>
  )
}
