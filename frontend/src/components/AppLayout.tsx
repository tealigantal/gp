import { Layout, Menu, theme, ConfigProvider } from 'antd'
import { Link, useLocation } from 'react-router-dom'
import { useMemo } from 'react'
import { lightTheme } from '../design/theme'

const { Header, Content, Footer } = Layout

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const loc = useLocation()
  const selected = useMemo(() => [
    loc.pathname.startsWith('/chat') ? 'chat' :
    loc.pathname.startsWith('/search') ? 'search' :
    loc.pathname.startsWith('/health') ? 'health' : 'convs'
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
              { key: 'convs', label: <Link to="/">会话</Link> },
              { key: 'chat', label: <Link to="/chat">对话</Link> },
              { key: 'search', label: <Link to="/search">搜索</Link> },
              { key: 'health', label: <Link to="/health">健康</Link> }
            ]}
            style={{ flex: 1, minWidth: 0 }}
          />
        </Header>
        <Content style={{ padding: '16px 24px' }}>
          <div style={{ background: token.colorBgContainer, padding: 24, minHeight: 360, maxWidth: 1280, margin: '0 auto', fontSize: 15, lineHeight: 1.7 }}>
            {children}
          </div>
        </Content>
        <Footer style={{ textAlign: 'center' }}>gp assistant · React SPA</Footer>
      </Layout>
    </ConfigProvider>
  )
}
