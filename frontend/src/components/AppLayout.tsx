import { Layout, Menu, theme, ConfigProvider } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { useMemo } from 'react'
import { lightTheme } from '../design/theme'
import { SelectedArtifactProvider } from '../features/artifacts/useSelectedArtifact'

const { Header, Content, Footer } = Layout

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  // Chat-first nav; Workbench is research page
  const selected = useMemo(() => {
    const p = loc.pathname
    const key = (p === '/' || p.startsWith('/chat') || p.startsWith('/pick')) ? 'chat'
      : p.startsWith('/compare') ? 'compare'
      : p.startsWith('/chat') ? 'chat'
      : p.startsWith('/health') ? 'health'
      : p.startsWith('/sim') ? 'sim'
      : 'chat'
    return [key]
  }, [loc.pathname])

  const algo = lightTheme.algorithm
  const { token } = theme.useToken()

  return (
    <ConfigProvider theme={{ algorithm: algo }}>
      <Layout className="app-shell" style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
        <Header style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ color: '#fff', fontWeight: 600, marginRight: 24 }}>gp assistant</div>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={selected}
            items={[
              { key: 'chat', label: <Link to="/chat">对话</Link> },
              { key: 'compare', label: <Link to="/compare">对比</Link> },
              { key: 'sim', label: <Link to="/sim">研究</Link> },
              { key: 'health', label: <Link to="/health">健康</Link> }
            ]}
            style={{ flex: 1, minWidth: 0 }}
          />
        </Header>
        {/* Content is scrollable so pages can extend vertically */}
        <Content className="app-content-shell" style={{ padding: '16px 24px', flex: 1, minHeight: 0, overflow: 'auto' }}>
          <div className="app-content-shell" style={{ background: token.colorBgContainer, padding: 24, height: '100%', maxWidth: 1400, margin: '0 auto', fontSize: 15, lineHeight: 1.7, display: 'flex', flexDirection: 'column', minHeight: 0, overflow: 'auto' }}>
            <SelectedArtifactProvider>
              {children}
            </SelectedArtifactProvider>
          </div>
        </Content>
        {/* Normal footer; does not cover interactive area */}
        <Footer style={{ textAlign: 'center' }}>gp assistant · React SPA</Footer>
      </Layout>
    </ConfigProvider>
  )
}
