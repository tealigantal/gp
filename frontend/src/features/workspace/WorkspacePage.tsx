import { Alert, Card, Layout, Spin } from 'antd'
import { useAdvisorWorkspace } from './useAdvisorWorkspace'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { DecisionSnapshot } from './components/DecisionSnapshot'
import { HeaderBar } from './components/HeaderBar'

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
    <>
      <a className="skip-link" href="#workspace-main">
        Skip to workspace
      </a>
      <Layout className="app-layout">
        <Header className="app-header">
          <HeaderBar
            sessionId={workspace.sessionId}
            onSessionIdChange={workspace.setSessionId}
            onNewSession={workspace.resetSession}
            health={workspace.health}
            book={workspace.book}
            sessions={workspace.sessions}
            isSessionSwitching={workspace.isSessionSwitching}
          />
        </Header>
        <Layout className="app-body chat-first">
          <Content className="center-pane">
            <main id="workspace-main" className="center-pane-main">
              {!workspace.health?.llm_ready ? (
                <Alert
                  type="error"
                  showIcon
                  message="LLM 当前不可用"
                  description="请检查后端配置，并确认 `/api/health` 返回 `llm_ready=true`。"
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              <Card
                className="chat-card"
                styles={{ body: { display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 } }}
              >
                <ChatThread
                  turns={workspace.turns}
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
              </Card>
            </main>
          </Content>
          <Sider width={360} theme="light" className="right-sider snapshot-sider" role="complementary" aria-label="Decision snapshot">
            <div className="panel-scroll">
              <DecisionSnapshot book={workspace.book} session={workspace.session} latest={workspace.latestResponse} />
            </div>
          </Sider>
        </Layout>
      </Layout>
    </>
  )
}
