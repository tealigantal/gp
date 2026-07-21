import { Alert, Card, Layout, Spin, Typography } from 'antd'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { DecisionSnapshot } from './components/DecisionSnapshot'
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
                        message={workspace.health?.llm_retryable ? '上一次自然语言回答未通过校验' : '自然语言助手尚未配置'}
                        description={
                          workspace.health?.llm_retryable
                            ? '被拒绝回答未展示也未保存。可直接重新提问，下一次仍走真实 LLM 与证据校验。'
                            : '请检查后端 LLM 配置后再发起对话。'
                        }
                      />
                    ) : null}
                    {showRuntimeAlert ? (
                      <Alert
                        className="workspace-alert"
                        type={workspace.health?.runtime?.book_freshness === 'lagging' ? 'warning' : 'info'}
                        showIcon
                        message="运行态提示"
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
                      <Typography.Text className="section-kicker">Conversation Workspace</Typography.Text>
                      <Typography.Title level={4} style={{ margin: 0 }}>
                        用一条连续对话，把推荐、执行、风控和变化都问清楚
                      </Typography.Title>
                      <Typography.Text className="section-subtitle">
                        直接追问今天的候选、为什么当前暂不入场、某只票还能不能买，或者上一轮为什么变了。
                      </Typography.Text>
                    </div>
                    <Typography.Text className="chat-card-caption">
                      {workspace.turns.length ? `已记录 ${workspace.turns.length} 条消息` : '从一句自然语言问题开始'}
                    </Typography.Text>
                  </div>
                  <ChatThread
                    turns={workspace.turns}
                    error={workspace.lastError}
                    sending={workspace.isSending}
                    onPrompt={prompt}
                  />
                  <Composer
                    value={workspace.composerValue}
                    onChange={workspace.setComposerValue}
                    onSubmit={() => workspace.submitMessage(workspace.composerValue)}
                    disabled={workspace.isSending}
                    llmReady={workspace.health?.llm_ready}
                    llmRetryable={workspace.health?.llm_retryable}
                  />
                </Card>
              </section>
            </main>
          </Content>
          <Sider
            width={440}
            theme="light"
            className="right-sider snapshot-sider"
            role="complementary"
            aria-label="Decision snapshot"
          >
            <aside className="snapshot-shell">
              <div className="panel-scroll">
                <DecisionSnapshot
                  book={workspace.book}
                  lunch={workspace.lunch}
                  latest={workspace.latestResponse}
                  health={workspace.health}
                  onRunTool={workspace.runTool}
                  onRefreshRuntime={workspace.refreshWorkspaceState}
                  runningToolService={workspace.runningToolService}
                  isRunningTool={workspace.isRunningTool}
                  opsResult={workspace.lastOpsResult}
                  opsError={workspace.lastOpsError}
                />
              </div>
            </aside>
          </Sider>
        </Layout>
      </Layout>
    </>
  )
}
