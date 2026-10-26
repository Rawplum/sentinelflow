import { createContext } from 'react'

import type { CurrentUser } from '../api/types'

export interface AuthContextValue {
  user: CurrentUser | null
  isAuthenticated: boolean
  isAdmin: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
