import { Alert, Card, Layout, Spin } from 'antd'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { DecisionSnapshot } from './components/DecisionSnapshot'
import { DebugDrawer } from './components/DebugDrawer'
import { HeaderBar } from './components/HeaderBar'
import { runtimeFreshnessMeta } from './runtimeLabels'
import { useAdvisorWorkspace } from './useAdvisorWorkspace'

const { Header, Sider, Content } = Layout

export function WorkspacePage() {
  const workspace = useAdvisorWorkspace()
  const runtimeFreshness = runtimeFreshnessMeta(workspace.health?.runtime)

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

  const showRuntimeAlert =
    workspace.health?.runtime?.book_freshness === 'lagging' ||
    workspace.health?.runtime?.book_freshness === 'degraded' ||
    workspace.health?.runtime?.book_freshness === 'unavailable'

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
                  type="warning"
                  showIcon
                  message="LLM 当前不可用"
                  description="结构化卡片和降级文案仍可用，但语义理解与自然解释会变弱。"
                  style={{ marginBottom: 12 }}
                />
              ) : null}
              {showRuntimeAlert ? (
                <Alert
                  type={workspace.health?.runtime?.book_freshness === 'lagging' ? 'warning' : 'info'}
                  showIcon
                  message="运行状态提示"
                  description={runtimeFreshness.note}
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
          <Sider width={376} theme="light" className="right-sider snapshot-sider" role="complementary" aria-label="Decision snapshot">
            <div className="panel-scroll">
              <DecisionSnapshot
                book={workspace.book}
                session={workspace.session}
                latest={workspace.latestResponse}
                health={workspace.health}
                onRunTool={workspace.runTool}
                onRefreshRuntime={workspace.refreshWorkspaceState}
                runningToolService={workspace.runningToolService}
                isRunningTool={workspace.isRunningTool}
                opsResult={workspace.lastOpsResult}
                opsError={workspace.lastOpsError}
              />
              <DebugDrawer
                session={workspace.session}
                diagnostics={workspace.diagnostics}
                latestResponse={workspace.latestResponse}
              />
            </div>
          </Sider>
        </Layout>
      </Layout>
    </>
  )
}
