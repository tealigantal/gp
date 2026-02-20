import { Alert, Badge, Card, Form, Input, InputNumber, Radio, Select, Space, Spin, Typography } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { recommend } from '../api/client'
import type { RecommendReq, RecommendResp } from '../api/types'
import { useEffect } from 'react'
import EnvBadge from '../components/EnvBadge'
import PicksTable from '../components/PicksTable'

const { Text } = Typography

export default function Recommend() {
  const [form] = Form.useForm()

  useEffect(() => {
    // defaults
    form.setFieldsValue({ topk: 3, universe: 'auto', risk_profile: 'normal', detail: 'compact' })
  }, [form])

  const m = useMutation({
    mutationFn: async (body: RecommendReq) => {
      const r = await recommend(body)
      return r
    }
  })

  const onFinish = (values: any) => {
    const symbols = typeof values.symbols === 'string' && values.symbols.trim().length > 0
      ? values.symbols.split(/[\s,，]+/).filter(Boolean)
      : undefined
    const body: RecommendReq = {
      topk: values.topk,
      universe: values.universe,
      symbols,
      risk_profile: values.risk_profile,
      detail: values.detail
    }
    m.mutate(body)
  }

  const data: RecommendResp | undefined = m.data
  const degraded = !!data?.debug?.degraded
  const reasons = data?.debug?.degrade_reasons || []

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="推荐参数">
        <Form form={form} layout="inline" onFinish={onFinish}>
          <Form.Item label="topk" name="topk" rules={[{ required: true }]}>
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item label="universe" name="universe">
            <Select style={{ width: 140 }} options={[{ label: 'auto', value: 'auto' }, { label: 'symbols', value: 'symbols' }]} />
          </Form.Item>
          <Form.Item label="symbols" name="symbols">
            <Input placeholder="以逗号或空格分隔，如 600519 000333" style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="risk" name="risk_profile">
            <Select style={{ width: 140 }} options={[{ value: 'normal' }, { value: 'conservative' }, { value: 'aggressive' }]} />
          </Form.Item>
          <Form.Item label="detail" name="detail" initialValue={'compact'}>
            <Radio.Group options={[{ label: 'compact', value: 'compact' }, { label: 'full', value: 'full' }]} />
          </Form.Item>
          <Form.Item>
            <button type="submit" className="ant-btn ant-btn-primary">查询</button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="结果">
        {m.isPending && <Spin />}
        {m.isError && <Alert type="error" message={(m.error as any)?.message || '请求失败'} />}
        {data && (
          <Space direction="vertical" style={{ width: '100%' }} size="middle">
            <Space align="center">
              <EnvBadge grade={data.env?.grade} tradeable={data.tradeable} />
              <Text type="secondary">{data.as_of}</Text>
            </Space>
            {degraded && (
              <Alert
                type="warning"
                showIcon
                message={<span>降级运行（debug.degraded=true）</span>}
                description={<div>
                  <div>原因代码：</div>
                  <ul style={{ marginTop: 8 }}>
                    {reasons.map((r, idx) => <li key={idx}><code>{r.reason_code}</code></li>)}
                  </ul>
                </div>}
              />
            )}
            <Card size="small" title="主题">
              {data.themes?.slice(0, 2).map((t, i) => (
                <Badge key={i} color={i === 0 ? 'green' : 'blue'} text={`${t.name} (${t.strength ?? '-'})`} style={{ marginRight: 12 }} />
              ))}
            </Card>
            <PicksTable picks={data.picks} loading={m.isPending} />
          </Space>
        )}
      </Card>
    </Space>
  )
}

