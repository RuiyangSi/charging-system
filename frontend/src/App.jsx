import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Login from './pages/Login.jsx'
import UserLayout from './pages/user/UserLayout.jsx'
import ChargePage from './pages/user/ChargePage.jsx'
import BillsPage from './pages/user/BillsPage.jsx'
import AdminLayout from './pages/admin/AdminLayout.jsx'
import MonitorPage from './pages/admin/MonitorPage.jsx'
import OpsPage from './pages/admin/OpsPage.jsx'
import RulesPage from './pages/admin/RulesPage.jsx'
import ReportsPage from './pages/admin/ReportsPage.jsx'
import FaultsPage from './pages/admin/FaultsPage.jsx'
import SettingsPage from './pages/admin/SettingsPage.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/user" element={<UserLayout />}>
          <Route index element={<Navigate to="charge" replace />} />
          <Route path="charge" element={<ChargePage />} />
          <Route path="bills" element={<BillsPage />} />
        </Route>
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<Navigate to="monitor" replace />} />
          <Route path="monitor" element={<MonitorPage />} />
          <Route path="ops" element={<OpsPage />} />
          <Route path="rules" element={<RulesPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="faults" element={<FaultsPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
