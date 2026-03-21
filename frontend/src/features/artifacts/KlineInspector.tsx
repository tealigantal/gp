import { Empty, Typography } from 'antd'
import { useSelectedArtifact } from './useSelectedArtifact'
import KlineView from '../kline/KlineView'

export default function KlineInspector() {
  const { panel, klineSymbol, klineOverlay } = useSelectedArtifact()
  if (panel !== 'kline') return <Empty description="选择右侧功能查看详情" />
  if (!klineSymbol) return <Typography.Text type="secondary">未选择标的</Typography.Text>
  return <KlineView symbol={klineSymbol} overlay={klineOverlay} />
}

