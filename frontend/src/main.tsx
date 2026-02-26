import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import 'antd/dist/reset.css'
import './design/global.css'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import { syncManager } from './sync/SyncManager'

dayjs.locale('zh-cn')

// Start low-frequency background sync once (idempotent), with proper cleanup on HMR/unload
try { syncManager.start(30000, 60000) } catch {}
window.addEventListener('beforeunload', () => { try { syncManager.stop() } catch {} })

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: 0 }
  }
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
