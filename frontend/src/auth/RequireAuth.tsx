import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from './useAuth'
import { Spinner } from '../components/ui/Spinner'

export function RequireAuth() {
  const { isAuthenticated, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="sf-full-page">
        <Spinner label="正在恢复会话…" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }

  return <Outlet />
}
