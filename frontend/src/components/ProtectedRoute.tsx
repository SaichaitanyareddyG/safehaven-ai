import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/lib/auth-context'

export function ProtectedRoute({ children, adminOnly = false }: { children: ReactNode; adminOnly?: boolean }) {
  const { user, isLoading } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return <div className="flex h-screen items-center justify-center text-sm text-muted-foreground">Loading…</div>
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  // Signed in with an admin's one-time password: nothing else until it is
  // replaced (the API refuses too — this just sends them to the right page).
  if (user.must_change_password) {
    return <Navigate to="/change-password" replace />
  }

  if (adminOnly && user.role !== 'admin') {
    return <Navigate to="/patients" replace />
  }

  return <>{children}</>
}
