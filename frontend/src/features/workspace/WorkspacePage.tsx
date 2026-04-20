import { Alert, Card, Layout, Spin } from 'antd'
import { useAdvisorWorkspace } from './useAdvisorWorkspace'
import { HeaderBar } from './components/HeaderBar'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { DecisionSnapshot } from './components/DecisionSnapshot'
import { DebugDrawer } from './components/DebugDrawer'

const { Header, Sider, Content } = Layout

export function WorkspacePage() {
  const workspace = useAdvisorWorkspace()
  const prompt = async (message: string) => {
    workspace.setComposerValue(message)
    await workspace.submitMessage(message)
  }

  if (workspace.isInitialLoading) {
    return (
      <div className="full-center">
        <Spin size="large" />
      </div>
    )
  }

  return (
    <Layout className="app-layout">
      <Header className="app-header">
        <HeaderBar
          sessionId={workspace.sessionId}
          onSessionIdChange={workspace.setSessionId}
          onNewSession={workspace.resetSession}
          health={workspace.health}
          bookVersion={workspace.book?.book_version || null}
          session={workspace.session}
          book={workspace.book}
          sessions={workspace.sessions}
        />
      </Header>
      <Layout className="app-body chat-first">
        <Content className="center-pane">
          {!workspace.health?.llm_ready ? (
            <Alert
              type="error"
              showIcon
              message="后端 LLM 不可用"
              description="请先确保 /api/health 返回 llm_ready=true"
              style={{ marginBottom: 12 }}
            />
          ) : null}
          <Card className="chat-card" bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
            <ChatThread
              turns={workspace.turns}
              latestResponse={workspace.latestResponse}
              error={workspace.lastError}
              sending={workspace.isSending}
              book={workspace.book}
              onPrompt={prompt}
            />
            <Composer
              value={workspace.composerValue}
              onChange={workspace.setComposerValue}
              onSubmit={() => workspace.submitMessage(workspace.composerValue)}
              disabled={workspace.isSending}
              llmReady={workspace.health?.llm_ready}
            />
            <DebugDrawer session={workspace.session} latestResponse={workspace.latestResponse} />
          </Card>
        </Content>
        <Sider width={360} theme="light" className="right-sider snapshot-sider">
          <div className="panel-scroll">
            <DecisionSnapshot book={workspace.book} session={workspace.session} latest={workspace.latestResponse} />
          </div>
        </Sider>
      </Layout>
    </Layout>
  )
}
