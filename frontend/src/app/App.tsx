import { ConfigProvider } from 'antd'
import { WorkspacePage } from '../features/workspace/WorkspacePage'

export default function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#2563eb',
          borderRadius: 10,
          fontFamily: 'Inter, PingFang SC, Microsoft YaHei, sans-serif',
        },
      }}
    >
      <WorkspacePage />
    </ConfigProvider>
  )
}
