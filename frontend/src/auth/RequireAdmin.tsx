import { Outlet } from 'react-router-dom'

import { useAuth } from './useAuth'
import { ForbiddenPage } from '../pages/ForbiddenPage'

export function RequireAdmin() {
  const { isAdmin } = useAuth()

  if (!isAdmin) {
    return <ForbiddenPage />
  }

  return <Outlet />
}
