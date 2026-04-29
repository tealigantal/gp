import { ConfigProvider } from 'antd'
import { WorkspacePage } from '../features/workspace/WorkspacePage'

export default function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#1d4ed8',
          colorInfo: '#1d4ed8',
          colorSuccess: '#1f7a57',
          colorWarning: '#c88719',
          borderRadius: 18,
          fontFamily: '"Aptos", "Segoe UI Variable", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
        components: {
          Button: {
            borderRadius: 999,
            controlHeight: 40,
          },
          Card: {
            borderRadiusLG: 24,
          },
        },
      }}
    >
      <WorkspacePage />
    </ConfigProvider>
  )
}
