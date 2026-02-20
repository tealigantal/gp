import { Layout, Menu, theme } from 'antd'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import Chat from './pages/Chat'
import Recommend from './pages/Recommend'
import Health from './pages/Health'

const { Header, Content, Footer } = Layout

export default function App() {
  const loc = useLocation()
  const selected = [
    loc.pathname.startsWith('/chat') ? 'chat' :
    loc.pathname.startsWith('/recommend') ? 'recommend' :
    loc.pathname.startsWith('/health') ? 'health' : 'recommend'
  ]
  const {
    token: { colorBgContainer }
  } = theme.useToken()

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <div style={{ color: '#fff', fontWeight: 600, marginRight: 24 }}>gp assistant</div>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={selected}
          items={[
            { key: 'recommend', label: <Link to="/recommend">推荐</Link> },
            { key: 'chat', label: <Link to="/chat">聊天</Link> },
            { key: 'health', label: <Link to="/health">健康</Link> }
          ]}
          style={{ flex: 1, minWidth: 0 }}
        />
      </Header>
      <Content style={{ padding: '16px 24px' }}>
        <div style={{ background: colorBgContainer, padding: 24, minHeight: 360 }}>
          <Routes>
            <Route path="/" element={<Recommend />} />
            <Route path="/recommend" element={<Recommend />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/health" element={<Health />} />
          </Routes>
        </div>
      </Content>
      <Footer style={{ textAlign: 'center' }}>gp assistant • React SPA</Footer>
    </Layout>
  )
}

