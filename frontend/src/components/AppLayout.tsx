import { Layout, Menu, theme, ConfigProvider } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { useMemo } from 'react'
import { lightTheme } from '../design/theme'
import { SelectedArtifactProvider } from '../features/artifacts/useSelectedArtifact'

const { Header, Content, Footer } = Layout

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const selected = useMemo(() => [
    loc.pathname.startsWith('/chat') ? 'chat' :
    loc.pathname.startsWith('/health') ? 'health' : 'history'
  ], [loc.pathname])

  const algo = lightTheme.algorithm
  const { token } = theme.useToken()

  return (
    <ConfigProvider theme={{ algorithm: algo }}>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ color: '#fff', fontWeight: 600, marginRight: 24 }}>gp assistant</div>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={selected}
            items={[
              { key: 'history', label: <Link to="/history">历史</Link> },
              { key: 'chat', label: <Link to="/chat">对话</Link> },
              { key: 'health', label: <Link to="/health">健康</Link> }
            ]}
            style={{ flex: 1, minWidth: 0 }}
          />
        </Header>
        {/* Content fills viewport minus header height; footer is fixed and does not reduce work area */}
        <Content style={{ padding: '16px 24px', height: 'calc(100vh - 64px)', overflow: 'hidden' }}>
          <div style={{ background: token.colorBgContainer, padding: 24, paddingBottom: 64, height: '100%', maxWidth: 1400, margin: '0 auto', fontSize: 15, lineHeight: 1.7, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            <SelectedArtifactProvider>
              {children}
            </SelectedArtifactProvider>
          </div>
        </Content>
        {/* Footer is fixed; it does not compete with main work area height */}
        <Footer style={{ textAlign: 'center', position: 'fixed', left: 0, right: 0, bottom: 0 }}>gp assistant · React SPA</Footer>
      </Layout>
    </ConfigProvider>
  )
}
