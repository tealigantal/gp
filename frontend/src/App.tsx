import { Route, Routes } from 'react-router-dom'
import Chat from './pages/Chat'
import Recommend from './pages/Recommend'
import Health from './pages/Health'
import Search from './pages/Search'
import Conversations from './pages/Conversations'
import AppLayout from './components/AppLayout'

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<Conversations />} />
        <Route path="/conversations" element={<Conversations />} />
        <Route path="/recommend" element={<Recommend />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/search" element={<Search />} />
        <Route path="/health" element={<Health />} />
      </Routes>
    </AppLayout>
  )
}
