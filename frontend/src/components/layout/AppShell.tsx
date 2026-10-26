import { Outlet } from 'react-router-dom'

import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell() {
  return (
    <div className="sf-shell">
      <Sidebar />
      <div className="sf-main">
        <Topbar />
        <main className="sf-content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
