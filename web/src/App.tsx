import { Routes, Route, HashRouter } from 'react-router-dom'
import SideNav from './components/SideNav'
import MarketPage from './pages/MarketPage'
import StrategiesPage from './pages/StrategiesPage'
import StrategyDetail from './pages/StrategyDetail'
import SignalDetail from './pages/SignalDetail'
import KnowledgePage from './pages/KnowledgePage'
import AdminImportsPage from './pages/AdminImportsPage'

export default function App() {
  return (
    <HashRouter>
      <div className="flex">
        <SideNav />
        <main className="flex-1" style={{ marginLeft: 56 }}>
          <Routes>
            <Route path="/" element={<MarketPage />} />
            <Route path="/market" element={<MarketPage />} />
            <Route path="/strategies" element={<StrategiesPage />} />
            <Route path="/knowledge" element={<KnowledgePage />} />
            <Route path="/admin/imports" element={<AdminImportsPage />} />
            <Route path="/strategies/:id" element={<StrategyDetail />} />
            <Route path="/signals/:id" element={<SignalDetail />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  )
}
