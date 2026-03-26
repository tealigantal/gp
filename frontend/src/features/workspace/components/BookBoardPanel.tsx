import { Button, Card, Empty, Space, Table, Tag, Tooltip, Typography } from 'antd'
import type { BoardEntry, MarketBook } from '../../../shared/contracts'
import { fmtNum, fmtPct, fmtTime, tagColorByExecution } from '../../../shared/format'

interface BookBoardPanelProps {
  book?: MarketBook
  onPrompt: (message: string) => void
}

export function BookBoardPanel({ book, onPrompt }: BookBoardPanelProps) {
  if (!book) {
    return <Card><Empty description="账本尚未就绪" /></Card>
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small" title="当前账本" extra={<Tag>{book.book_version}</Tag>}>
        <Space wrap>
          <Tag color={book.daybook.tradeable ? 'green' : 'orange'}>{book.daybook.tradeable ? '可交易' : '偏观察'}</Tag>
          <Tag>{book.trading_day}</Tag>
          <Tag>5m: {fmtTime(book.last_closed_5m)}</Tag>
          {book.daybook.themes.slice(0, 4).map((theme) => <Tag key={theme}>{theme}</Tag>)}
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          {book.daybook.reason || '当前 Board 由日线骨架与 5 分滚动状态合成。'}
        </Typography.Paragraph>
      </Card>
      <Card size="small" title="Board · 当前可行动排序">
        <Table<BoardEntry>
          size="small"
          rowKey="symbol"
          pagination={false}
          dataSource={book.board}
          scroll={{ x: 900, y: 520 }}
          columns={[
            {
              title: '#',
              dataIndex: 'rank',
              width: 48,
            },
            {
              title: '标的',
              key: 'symbol',
              width: 140,
              render: (_, entry) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text strong>{entry.symbol}</Typography.Text>
                  <Typography.Text type="secondary">{entry.name || '—'}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '状态',
              key: 'state',
              width: 150,
              render: (_, entry) => (
                <Space wrap>
                  <Tag color={tagColorByExecution(entry.execution_state)}>{entry.execution_state}</Tag>
                  {entry.can_open ? <Tag color="green">can_open</Tag> : null}
                  {entry.invalidated ? <Tag color="red">invalidated</Tag> : null}
                </Space>
              ),
            },
            {
              title: '分数',
              key: 'scores',
              width: 160,
              render: (_, entry) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text>final {fmtNum(entry.final_score)}</Typography.Text>
                  <Typography.Text type="secondary">live {fmtNum(entry.live_score)}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '5m',
              key: 'pulse',
              width: 200,
              render: (_, entry) => (
                <Space direction="vertical" size={0}>
                  <Typography.Text>pulse {fmtNum(entry.pulse?.pulse_score)}</Typography.Text>
                  <Typography.Text type="secondary">dist {fmtPct((entry.pulse?.entry_distance_pct ?? null) != null ? (entry.pulse?.entry_distance_pct ?? 0) / 100 : null)}</Typography.Text>
                </Space>
              ),
            },
            {
              title: '摘要',
              dataIndex: 'summary',
            },
            {
              title: '操作',
              key: 'actions',
              width: 220,
              render: (_, entry) => (
                <Space wrap>
                  <Button size="small" onClick={() => onPrompt(`看看 ${entry.symbol} 现在还能买吗`)}>跟踪</Button>
                  <Button size="small" onClick={() => onPrompt(`比较 ${entry.symbol} 和 ${book.board[0]?.symbol || entry.symbol}`)}>比较</Button>
                  <Tooltip title="把该票作为对话焦点，直接追问 thesis / 风险 / 执行区间">
                    <Button size="small" onClick={() => onPrompt(`为什么把 ${entry.symbol} 放进当前 board`)}>为什么</Button>
                  </Tooltip>
                </Space>
              ),
            },
          ]}
        />
      </Card>
    </Space>
  )
}
