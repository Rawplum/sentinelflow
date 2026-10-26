import { LogOut } from 'lucide-react'

import { useAuth } from '../../auth/useAuth'
import { RoleBadge } from '../domain/Badges'

export function Topbar() {
  const { user, logout } = useAuth()

  return (
    <header className="sf-topbar">
      <div className="sf-topbar-context">
        <span className="sf-status-dot" aria-hidden="true" />
        <span>LOCAL CONTROL PLANE</span>
      </div>
      <div className="sf-topbar-user">
        <div className="sf-user-meta">
          <span className="sf-user-name">{user?.username ?? 'unknown'}</span>
          <RoleBadge role={user?.role} />
        </div>
        <button
          type="button"
          className="sf-btn sf-btn-ghost sf-btn-sm"
          onClick={logout}
        >
          <LogOut size={15} aria-hidden="true" />
          <span>退出</span>
        </button>
      </div>
    </header>
  )
}
