import { Alert, Card, Descriptions, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { health } from '../api/client'

export default function Health() {
  const q = useQuery({ queryKey: ['health'], queryFn: health, refetchInterval: 15000 })
  return (
    <Card title="系统健康">
      {q.isLoading && <Spin />}
      {q.isError && <Alert type="error" message={(q.error as any)?.message || '请求失败'} />}
      {q.data && (
        <Descriptions bordered column={1} size="small">
          <Descriptions.Item label="状态">{q.data.status}</Descriptions.Item>
          <Descriptions.Item label="LLM 准备度">{q.data.llm_ready ? '是' : '否'}</Descriptions.Item>
          <Descriptions.Item label="时间戳">{q.data.time}</Descriptions.Item>
          <Descriptions.Item label="Provider">
            <pre style={{ margin: 0 }}>{JSON.stringify(q.data.provider, null, 2)}</pre>
          </Descriptions.Item>
        </Descriptions>
      )}
    </Card>
  )
}

