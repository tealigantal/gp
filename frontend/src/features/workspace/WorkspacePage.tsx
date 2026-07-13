import { Alert, Card, Layout, Spin, Typography } from 'antd'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { HeaderBar } from './components/HeaderBar'
import { useAdvisorWorkspace } from './useAdvisorWorkspace'

const { Header, Content } = Layout

export function WorkspacePage() {
  const workspace = useAdvisorWorkspace()
  if (workspace.isInitialLoading) return <div className="full-center"><Spin size="large" /></div>
  return <Layout className="app-layout"><Header className="app-header"><HeaderBar health={workspace.health} onNewSession={workspace.resetSession} /></Header><Content className="center-pane"><main className="center-pane-main"><Card className="chat-card" styles={{ body: { display: 'flex', flexDirection: 'column', gap: 18 } }}>
    <Typography.Title level={4} style={{ margin: 0 }}>围绕同一份当前荐股快照连续追问</Typography.Title>
    {!workspace.health?.current_snapshot ? <Alert type="warning" showIcon message="当前没有有效快照，系统会明确返回 no_trade。" /> : null}
    <ChatThread turns={workspace.turns} error={workspace.lastError} sending={workspace.isSending} />
    <Composer value={workspace.composerValue} onChange={workspace.setComposerValue} onSubmit={() => workspace.submitMessage(workspace.composerValue)} disabled={workspace.isSending} llmReady />
  </Card></main></Content></Layout>
}
