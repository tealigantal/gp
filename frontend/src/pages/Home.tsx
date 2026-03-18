import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, List, Space, Tag, Typography, message } from 'antd'
import WorkbenchLayout from '../components/WorkbenchLayout'
import { getRecommendV2Gated } from '../api/client'
import type { PickV2Item, RecommendV2 } from '../api/types'
import { useNavigate } from 'react-router-dom'
import AssistantPanel from '../components/AssistantPanel'

const { Text, Title } = Typography

export default function Home() {
  const [data, setData] = useState<RecommendV2 | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const nav = useNavigate()

  useEffect(() => {
    async function load() {
      setLoading(true); setError(null)
      try {
        const d = await getRecommendV2Gated()
        setData(d)
      } catch (e: any) {
        setError(e?.message || String(e))
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const picks = useMemo(() => (data?.items || []) as PickV2Item[], [data])

  function toggleSelect(sym: string) {
    setSelected((cur) => cur.includes(sym) ? cur.filter((s) => s !== sym) : (cur.length >= 3 ? cur : [...cur, sym]))
  }

  const left = (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div className="workbench-scroll">
        <Card size="small" title="今日市场 / 系统概览" bordered={false} style={{ marginBottom: 12 }}>
          {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 8 }} />}
          <Space direction="vertical" size={8}>
            <Text type="secondary">as_of: {data?.as_of || '-'}</Text>
            <Space wrap>
              <Tag color={data?.tradeable ? 'green' : 'default'}>{data?.tradeable ? '可交易' : '不交易'}</Tag>
              {data?.market_regime && <Tag color="geekblue">regime: {data.market_regime}</Tag>}
              {data?.run_gating?.decision && <Tag color={data.run_gating.decision === 'allow' ? 'green' : data.run_gating.decision === 'degraded' ? 'orange' : 'red'}>{data.run_gating.decision}</Tag>}
            </Space>
            {Array.isArray(data?.run_gating?.warnings) && data!.run_gating!.warnings!.length > 0 && (
              <Text type="warning">warnings: {data!.run_gating!.warnings!.slice(0, 3).join('，')}</Text>
            )}
            {Array.isArray(data?.themes) && data!.themes!.length > 0 && (
              <div>
                <Text type="secondary">themes:</Text>
                <div style={{ marginTop: 4 }}>
                  <Space size={[8, 8]} wrap>
                    {data!.themes!.slice(0, 12).map((t) => (<Tag key={t}>{t}</Tag>))}
                  </Space>
                </div>
              </div>
            )}
          </Space>
        </Card>
        <Card size="small" title="操作" bordered={false}>
          <Space>
            <Button type="primary" disabled={selected.length < 2} onClick={() => nav(`/compare?symbols=${encodeURIComponent(selected.join(','))}`)}>对比所选（{selected.length}/3）</Button>
            <Button disabled={!selected.length} onClick={() => setSelected([])}>清空选择</Button>
          </Space>
        </Card>
      </div>
    </div>
  )

  const center = (
    <div className="workbench-scroll" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Title level={4} style={{ margin: 0 }}>Top Picks / 推荐列表</Title>
        <Text type="secondary">根据最新运行排名的可操作机会</Text>
      </div>
      <Card size="small" loading={loading}>
        <List
          dataSource={picks}
          renderItem={(it) => (
            <List.Item
              key={it.symbol}
              actions={[
                <a key="detail" onClick={() => nav(`/pick/${encodeURIComponent(it.symbol)}`)}>详情</a>,
                <a key="sel" onClick={() => toggleSelect(it.symbol)}>{selected.includes(it.symbol) ? '取消对比' : '加入对比'}</a>,
              ]}
            >
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                  <Space wrap>
                    <Text strong>{it.symbol}{it.name ? ` · ${it.name}` : ''}</Text>
                    {it.strategy_label && <Tag color="blue">{it.strategy_label}</Tag>}
                    {it.execution_state && <Tag color={it.execution_state === 'actionable' ? 'green' : 'default'}>{it.execution_state}</Tag>}
                    {typeof it.confidence === 'number' && <Tag color="purple">conf {it.confidence.toFixed(2)}</Tag>}
                    {typeof it.reliability_score === 'number' && <Tag>rel {it.reliability_score.toFixed(2)}</Tag>}
                    {typeof it.final_score === 'number' && <Tag color="gold">score {it.final_score.toFixed(2)}</Tag>}
                  </Space>
                  <div>
                    <Button size="small" type={selected.includes(it.symbol) ? 'primary' : 'default'} onClick={() => toggleSelect(it.symbol)}>
                      {selected.includes(it.symbol) ? '已选' : '对比'}
                    </Button>
                  </div>
                </div>
                {it.thesis && <div style={{ marginTop: 4 }}><Text type="secondary">{it.thesis}</Text></div>}
                <div style={{ marginTop: 8, color: 'rgba(0,0,0,0.65)' }}>
                  <Space wrap size={[12, 8]}>
                    {typeof it.price_ref === 'number' && <div>现价: {it.price_ref.toFixed(2)}</div>}
                    {Array.isArray(it.entry_zone) && <div>买点: {it.entry_zone.map((v) => (v ?? '-') as number).map((v) => Number(v).toFixed(2)).join(' / ')}</div>}
                    {typeof it.stop === 'number' && <div>止损: {it.stop.toFixed(2)}</div>}
                    {Array.isArray(it.take_profit) && it.take_profit.length > 0 && <div>止盈: {it.take_profit.map((v) => Number(v).toFixed(2)).join(' / ')}</div>}
                    {typeof it.reward_risk === 'number' && <div>RR: {it.reward_risk.toFixed(2)}</div>}
                  </Space>
                </div>
              </div>
            </List.Item>
          )}
        />
        {!loading && picks.length === 0 && <div style={{ textAlign: 'center' }}><Text type="secondary">暂无推荐</Text></div>}
      </Card>
    </div>
  )

  const right = (
    <div className="workbench-scroll">
      <Typography.Paragraph type="secondary">
        首页信息仅用于研究参考。推荐与执行请前往“对话”。
      </Typography.Paragraph>
    </div>
  )

  return (
    <WorkbenchLayout left={left} center={center} right={right} />
  )
}
