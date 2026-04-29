import { Alert, Card, Layout, Spin, Typography } from 'antd'
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
    workspace.health?.runtime?.intraday_runtime_enabled !== false &&
    (workspace.health?.runtime?.book_freshness === 'lagging' ||
      workspace.health?.runtime?.book_freshness === 'degraded' ||
      workspace.health?.runtime?.book_freshness === 'unavailable')

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
              <section className="workspace-stack" aria-label="Advisor conversation workspace">
                {!workspace.health?.llm_ready || showRuntimeAlert ? (
                  <div className="workspace-alert-stack" aria-live="polite">
                    {!workspace.health?.llm_ready ? (
                      <Alert
                        className="workspace-alert workspace-alert-warning"
                        type="warning"
                        showIcon
                        message="LLM 当前不可用"
                        description="结构化卡片和降级文案仍可用，但语义理解与自然解释会变弱。"
                      />
                    ) : null}
                    {showRuntimeAlert ? (
                      <Alert
                        className="workspace-alert"
                        type={workspace.health?.runtime?.book_freshness === 'lagging' ? 'warning' : 'info'}
                        showIcon
                        message="运行状态提示"
                        description={runtimeFreshness.note}
                      />
                    ) : null}
                  </div>
                ) : null}
                <Card
                  className="chat-card"
                  styles={{ body: { display: 'flex', flexDirection: 'column', gap: 18, minHeight: 0 } }}
                >
                  <div className="chat-card-header">
                    <div>
                      <Typography.Title level={4} style={{ margin: 0 }}>
                        对话工作区
                      </Typography.Title>
                      <Typography.Text className="section-subtitle">
                        直接问机会、买点、盘中执行、风控和前后 run 变化。
                      </Typography.Text>
                    </div>
                    <Typography.Text className="chat-card-caption">
                      {workspace.turns.length ? `${workspace.turns.length} 条消息` : '从一个问题开始'}
                    </Typography.Text>
                  </div>
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
              </section>
            </main>
          </Content>
          <Sider
            width={392}
            theme="light"
            className="right-sider snapshot-sider"
            role="complementary"
            aria-label="Decision snapshot"
          >
            <aside className="snapshot-shell">
              <div className="snapshot-shell-header">
                <Typography.Title level={4} style={{ margin: 0 }}>
                  决策控制台
                </Typography.Title>
                <Typography.Text className="section-subtitle">
                  看运行时、手工恢复工具、当前计划和 top symbols。
                </Typography.Text>
              </div>
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
            </aside>
          </Sider>
        </Layout>
      </Layout>
    </>
  )
}
