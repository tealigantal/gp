import { useEffect, useState } from 'react'
import { Badge, Button, Card, List, Space, Typography, Popconfirm, message } from 'antd'
import { syncManager } from '../sync/SyncManager'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { deleteConversation, cleanupConversations } from '../api/client'

type Item = { id: string; title: string; lastSeq: number; updatedAt?: string; unread: number; preview: string }

function newSessId() {
  return 'sess-' + Date.now().toString().slice(0, 10)
}

export default function Conversations() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()

  useEffect(() => {
    const unsub = syncManager.subscribe(() => setItems(syncManager.convList() as Item[]))
    setItems(syncManager.convList() as Item[])
    syncManager.start()
    return () => unsub()
  }, [])

  async function refresh() {
    setLoading(true)
    try { await syncManager.flush() } finally { setLoading(false) }
  }

  function open(cid: string) {
    localStorage.setItem('gp_session_id', cid)
    nav(`/chat?cid=${encodeURIComponent(cid)}`)
  }

  async function onDelete(cid: string) {
    try {
      await deleteConversation(cid)
      message.success('已删除会话')
      // 立刻从列表移除
      setItems((prev) => prev.filter((x) => x.id !== cid))
      // 触发一次同步以刷新 meta
      await syncManager.flush()
    } catch (e: any) {
      message.error(e?.message || '删除失败')
    }
  }

  function createNew() {
    const id = newSessId()
    localStorage.setItem('gp_session_id', id)
    nav(`/chat?cid=${encodeURIComponent(id)}`)
  }

  async function cleanupAll() {
    try {
      await cleanupConversations('all')
      message.success('已清理所有会话')
      setItems([])
      // 同时清理本地缓存
      ;['gp_session_id','gp_sync_cursors','gp_sync_outbox','gp_sync_last_read'].forEach((k)=>localStorage.removeItem(k))
      await syncManager.flush()
    } catch (e: any) {
      message.error(e?.message || '清理失败')
    }
  }

  return (
    <Card title="会话" extra={<Space>
      <Popconfirm title="清理所有会话" description="将删除服务器上的全部会话及消息，不可恢复。确认？" onConfirm={cleanupAll}>
        <Button danger>一键清理</Button>
      </Popconfirm>
      <Button onClick={createNew} type="primary">新建对话</Button>
      <Button loading={loading} onClick={refresh}>刷新</Button>
    </Space>}>
      <List
        dataSource={items}
        renderItem={(it) => (
          <List.Item style={{ cursor: 'pointer' }} actions={[
            <Popconfirm key="del" title="删除会话" description="此操作不可恢复，确定删除？" onConfirm={() => onDelete(it.id)}>
              <Button danger size="small" onClick={(e) => e.stopPropagation()}>删除</Button>
            </Popconfirm>
          ]} onClick={(e) => {
            // 避免点到删除按钮触发打开
            if ((e.target as HTMLElement).closest('.ant-popover') || (e.target as HTMLElement).closest('button')) return
            open(it.id)
          }}>
            <Space direction="vertical" style={{ width: '100%' }} size={0}>
              <Space align="center" style={{ justifyContent: 'space-between', width: '100%' }}>
                <Typography.Text strong>{it.title}</Typography.Text>
                <Space>
                  {it.unread > 0 && <Badge count={it.unread} style={{ backgroundColor: '#f5222d' }} />}
                  <Typography.Text type="secondary">{it.updatedAt ? dayjs(it.updatedAt).format('MM-DD HH:mm') : ''}</Typography.Text>
                </Space>
              </Space>
              <Typography.Paragraph type="secondary" ellipsis={{ rows: 1 }} style={{ marginBottom: 0 }}>
                {it.preview || '...'}
              </Typography.Paragraph>
            </Space>
          </List.Item>
        )}
      />
    </Card>
  )
}
