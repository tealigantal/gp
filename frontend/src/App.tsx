import { Route, Routes, Navigate } from 'react-router-dom'
import Chat from './pages/Chat'
import Health from './pages/Health'
import Workbench from './pages/Workbench'
import PickDetail from './pages/PickDetail'
import Compare from './pages/Compare'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/pick/:symbol" element={<PickDetail />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/health" element={<Health />} />
        <Route path="/sim" element={<Workbench />} />
      </Routes>
    </AppLayout>
  )
}
