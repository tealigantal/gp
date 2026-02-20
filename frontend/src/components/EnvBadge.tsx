import { Badge, Space, Tag } from 'antd'

export default function EnvBadge({ grade, tradeable }: { grade?: string; tradeable?: boolean }) {
  const colorByGrade: Record<string, string> = { A: 'green', B: 'blue', C: 'orange', D: 'red' }
  const g = (grade || 'C').toUpperCase()
  const color = colorByGrade[g] || 'default'
  return (
    <Space>
      <Tag color={color}>环境 {g}</Tag>
      <Badge status={tradeable ? 'success' : 'warning'} text={tradeable ? '可交易' : '不可交易'} />
    </Space>
  )
}

