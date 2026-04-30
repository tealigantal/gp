import { ConfigProvider } from 'antd'
import { WorkspacePage } from '../features/workspace/WorkspacePage'

export default function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#2457d6',
          colorInfo: '#2457d6',
          colorSuccess: '#2b8a63',
          colorWarning: '#d08c24',
          borderRadius: 20,
          fontFamily: '"Aptos", "Segoe UI Variable", "SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
        components: {
          Button: {
            borderRadius: 999,
            controlHeight: 42,
          },
          Card: {
            borderRadiusLG: 26,
          },
        },
      }}
    >
      <WorkspacePage />
    </ConfigProvider>
  )
}
