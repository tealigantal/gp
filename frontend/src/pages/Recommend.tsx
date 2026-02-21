import { Alert, Badge, Card, Form, Input, InputNumber, Radio, Select, Space, Spin, Typography } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { recommend } from '../api/client'
import type { RecommendReq, RecommendResp } from '../api/types'
import { useEffect } from 'react'
import EnvBadge from '../components/EnvBadge'
import PicksTable from '../components/PicksTable'
import DegradeAlert from '../components/DegradeAlert'
import KlineChart from '../components/KlineChart'

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
  const firstSymbol = data?.picks?.[0]?.symbol

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="large">
      <Card title="推荐参数">
        <Form form={form} layout="inline" onFinish={onFinish}>
          <Form.Item label="返回数量" name="topk" tooltip="返回多少只候选（1-10）" rules={[{ required: true }] }>
            <InputNumber min={1} max={10} />
          </Form.Item>
          <Form.Item label="股票池" name="universe" tooltip="数据来源：自动从市场筛选，或仅评估指定代码">
            <Select
              style={{ width: 140 }}
              options={[
                { label: '自动', value: 'auto' },
                { label: '指定列表', value: 'symbols' }
              ]}
            />
          </Form.Item>
          <Form.Item label="股票代码" name="symbols" tooltip="当选择‘指定列表’时生效；用空格或逗号分隔">
            <Input placeholder="以逗号或空格分隔，如 600519 000333" style={{ width: 300 }} />
          </Form.Item>
          <Form.Item label="风险偏好" name="risk_profile" tooltip="仅用于结果说明，不改变核心数据链路">
            <Select
              style={{ width: 140 }}
              options={[
                { label: '正常', value: 'normal' },
                { label: '保守', value: 'conservative' },
                { label: '激进', value: 'aggressive' }
              ]}
            />
          </Form.Item>
          <Form.Item label="结果详略" name="detail" tooltip="轻量：只保留关键信息；完整：包含调试与详细字段" initialValue={'compact'}>
            <Radio.Group options={[{ label: '轻量', value: 'compact' }, { label: '完整', value: 'full' }]} />
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
            {degraded && <DegradeAlert reasons={reasons as any} />}
            {firstSymbol && (
              <Card size="small" title={`K 线：${firstSymbol}`}>
                <KlineChart symbol={firstSymbol} />
              </Card>
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
