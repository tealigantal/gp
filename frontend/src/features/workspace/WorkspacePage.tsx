import { Alert, Card, Layout, Spin, Tabs } from 'antd'
import { useAdvisorWorkspace } from './useAdvisorWorkspace'
import { HeaderBar } from './components/HeaderBar'
import { ChatThread } from './components/ChatThread'
import { Composer } from './components/Composer'
import { BookBoardPanel } from './components/BookBoardPanel'
import { RunPanel } from './components/RunPanel'
import { SessionPanel } from './components/SessionPanel'
import { SideResultsPanel } from './components/SideResultsPanel'
import { QuickPrompts } from './components/QuickPrompts'

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
        />
      </Header>
      <Layout className="app-body">
        <Sider width={320} theme="light" className="left-sider">
          <div className="panel-scroll">
            {!workspace.health?.llm_ready ? (
              <Alert
                type="error"
                showIcon
                message="后端 LLM 不可用"
                description="前端不会做旧链路兼容或静态兜底；请先让 /api/health 返回 llm_ready=true。"
                style={{ marginBottom: 12 }}
              />
            ) : null}
            <QuickPrompts book={workspace.book} run={workspace.run} onPrompt={prompt} />
            <div style={{ height: 12 }} />
            <SessionPanel session={workspace.session} />
          </div>
        </Sider>
        <Content className="center-pane">
          <Card className="chat-card" bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 16, minHeight: 0 }}>
            <ChatThread
              turns={workspace.turns}
              latestResponse={workspace.latestResponse}
              error={workspace.lastError}
              sending={workspace.isSending}
            />
            <Composer
              value={workspace.composerValue}
              onChange={workspace.setComposerValue}
              onSubmit={() => workspace.submitMessage(workspace.composerValue)}
              disabled={workspace.isSending}
              llmReady={workspace.health?.llm_ready}
            />
          </Card>
        </Content>
        <Sider width={480} theme="light" className="right-sider">
          <div className="panel-scroll">
            <Tabs
              defaultActiveKey="board"
              items={[
                {
                  key: 'board',
                  label: 'Board',
                  children: <BookBoardPanel book={workspace.book} onPrompt={prompt} />,
                },
                {
                  key: 'run',
                  label: 'Active Run',
                  children: <RunPanel run={workspace.run} onPrompt={prompt} />,
                },
                {
                  key: 'signals',
                  label: 'Side Results',
                  children: <SideResultsPanel items={workspace.sideResults} />,
                },
              ]}
            />
          </div>
        </Sider>
      </Layout>
    </Layout>
  )
}
