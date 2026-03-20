import { Route, Routes, Navigate } from 'react-router-dom'
import Chat from './pages/Chat'
import Health from './pages/Health'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/health" element={<Health />} />
      </Routes>
    </AppLayout>
  )
}
