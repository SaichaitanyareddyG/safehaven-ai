import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'

import { getCurrentUser, login as apiLogin } from '@/api/auth'
import { clearToken, getToken, setToken } from '@/lib/auth-storage'
import type { UserRead } from '@/types/auth'

interface AuthContextValue {
  user: UserRead | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  /** Sign in with a token already issued, e.g. by choosing a password from a link. */
  signInWithToken: (token: string) => Promise<void>
  /** Re-read the signed-in user, e.g. after a password change or the tour. */
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserRead | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    if (!getToken()) {
      setIsLoading(false)
      return
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setIsLoading(false))
  }, [])

  async function login(email: string, password: string) {
    const { access_token } = await apiLogin({ email, password })
    setToken(access_token)
    const me = await getCurrentUser()
    setUser(me)
  }

  async function signInWithToken(token: string) {
    setToken(token)
    setUser(await getCurrentUser())
  }

  async function refreshUser() {
    setUser(await getCurrentUser())
  }

  function logout() {
    clearToken()
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, isLoading, login, logout, signInWithToken, refreshUser }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
