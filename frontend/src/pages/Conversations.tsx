import { useEffect, useState } from "react"
import { Badge, Button, Card, List, Space, Typography, Popconfirm, message } from "antd"
import dayjs from "dayjs"
import { useNavigate } from "react-router-dom"
import { deleteConversation, cleanupConversations, getConversationSummaries } from "../api/client"
import { asConversationSummary } from "../api/adapters"
import type { ConversationSummary } from "../api/contracts"
import { setSessionId as persistSessionId, newSid } from "../utils/session"

type Item = { id: string; title: string; lastSeq: number; updatedAt?: string | null; unread: number; preview: string }

export default function Conversations() {
  const [items, setItems] = useState<Item[]>([])
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()

  async function load() {
    setLoading(true)
    try {
      const data = await getConversationSummaries()
      const list = (data || []).map(asConversationSummary)
      setItems(
        list
          .map((m: ConversationSummary) => ({
            id: m.id,
            title: m.title || m.id,
            lastSeq: m.last_seq,
            updatedAt: m.updated_at,
            unread: m.unread_count,
            preview: m.last_item_preview || "",
          }))
          .sort((a, b) => {
            const ta = a.updatedAt ? Date.parse(a.updatedAt) : 0
            const tb = b.updatedAt ? Date.parse(b.updatedAt) : 0
            if (tb !== ta) return tb - ta
            return b.lastSeq - a.lastSeq
          })
      )
    } catch (e: any) {
      message.error(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function refresh() {
    setLoading(true)
    try { await load() } finally { setLoading(false) }
  }

  function open(cid: string) {
    persistSessionId(cid)
    nav(`/chat?cid=${encodeURIComponent(cid)}`)
  }

  async function onDelete(cid: string) {
    try {
      await deleteConversation(cid)
      message.success('已删除会话')
      await load()
    } catch (e: any) {
      message.error(e?.message || '删除失败')
    }
  }

  function createNew() {
    const id = newSid()
    persistSessionId(id)
    nav(`/chat?cid=${encodeURIComponent(id)}`)
  }

  async function cleanupAll() {
    try {
      await cleanupConversations('all')
      message.success('已清理所有会话')
      setItems([])
      ;['gp:lastSid','gp_session_id'].forEach((k)=>localStorage.removeItem(k))
      await load()
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
