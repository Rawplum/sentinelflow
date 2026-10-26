import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'

import { getCurrentUser, login as loginRequest } from '../api/auth'
import { setAccessToken, setUnauthorizedHandler } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AuthContext } from './authState'
import type { AuthContextValue } from './authState'
import { clearSession, readSession, writeSession } from './tokenStorage'

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps) {
  const navigate = useNavigate()
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isLoading, setIsLoading] = useState<boolean>(() => {
    const session = readSession()
    return Boolean(session && session.expiresAt > Date.now())
  })
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clearAuth = useCallback(
    (redirect: boolean) => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      clearSession()
      setAccessToken(null)
      setUser(null)
      if (redirect) {
        navigate('/login', {
          replace: true,
          state: { reason: 'expired' },
        })
      }
    },
    [navigate],
  )

  const scheduleExpiry = useCallback(
    (expiresAt: number) => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
      const remaining = expiresAt - Date.now()
      if (remaining <= 0) {
        clearAuth(true)
        return
      }
      timerRef.current = setTimeout(() => clearAuth(true), remaining)
    },
    [clearAuth],
  )

  useEffect(() => {
    const session = readSession()
    if (!session || session.expiresAt <= Date.now()) {
      clearSession()
      return
    }

    let cancelled = false
    setAccessToken(session.accessToken)

    getCurrentUser()
      .then((currentUser) => {
        if (cancelled) return
        setUser(currentUser)
        scheduleExpiry(session.expiresAt)
      })
      .catch(() => {
        if (cancelled) return
        clearSession()
        setAccessToken(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [scheduleExpiry])

  useEffect(() => {
    setUnauthorizedHandler(() => clearAuth(true))
    return () => setUnauthorizedHandler(null)
  }, [clearAuth])

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [])

  const login = useCallback(
    async (username: string, password: string) => {
      const tokenResponse = await loginRequest(username, password)
      const expiresAt = Date.now() + tokenResponse.expires_in * 1000

      setAccessToken(tokenResponse.access_token)
      writeSession({ accessToken: tokenResponse.access_token, expiresAt })
      scheduleExpiry(expiresAt)

      try {
        const currentUser = await getCurrentUser()
        setUser(currentUser)
      } catch (error) {
        clearAuth(false)
        throw error
      }
    },
    [clearAuth, scheduleExpiry],
  )

  const logout = useCallback(() => {
    clearAuth(false)
    navigate('/login', { replace: true })
  }, [clearAuth, navigate])

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isAdmin: user?.role === 'admin',
      isLoading,
      login,
      logout,
    }),
    [user, isLoading, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
