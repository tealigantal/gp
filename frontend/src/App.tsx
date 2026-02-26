import { Route, Routes } from 'react-router-dom'
import Chat from './pages/Chat'
import Health from './pages/Health'
import History from './pages/History'
import { Navigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<History />} />
        <Route path="/history" element={<History />} />
        <Route path="/conversations" element={<Navigate to="/history?tab=sessions" replace />} />
        <Route path="/search" element={<Navigate to="/history?tab=search" replace />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/health" element={<Health />} />
      </Routes>
    </AppLayout>
  )
}
