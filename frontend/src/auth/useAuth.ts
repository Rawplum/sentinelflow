import { useContext } from 'react'

import { AuthContext } from './authState'
import type { AuthContextValue } from './authState'

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
