import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { RenderResult } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import App from '../App'
import type { AuthContextValue } from '../auth/authState'
import { AuthContext } from '../auth/authState'
import type { CurrentUser } from '../api/types'
import { adminUser, analystUser } from './msw/handlers'

export function makeAuth(
  overrides: Partial<AuthContextValue> = {},
): AuthContextValue {
  const user = overrides.user ?? adminUser
  return {
    user,
    isAuthenticated: user !== null,
    isAdmin: user?.role === 'admin',
    isLoading: false,
    login: vi.fn().mockResolvedValue(undefined),
    logout: vi.fn(),
    ...overrides,
  }
}

export const adminAuth = makeAuth()
export const analystAuth = makeAuth({
  user: analystUser,
  isAdmin: false,
})
export const unauthenticatedAuth = makeAuth({
  user: null as CurrentUser | null,
  isAuthenticated: false,
  isAdmin: false,
})

export function renderApp(
  initialPath: string,
  auth: AuthContextValue = adminAuth,
): RenderResult {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <AuthContext.Provider value={auth}>
          <App />
        </AuthContext.Provider>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
