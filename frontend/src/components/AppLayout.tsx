import { HeartPulse, LogOut, ScanLine } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useAuth } from '@/lib/auth-context'

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-muted/30">
      <header className="border-b bg-background">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/patients" className="flex items-center gap-2 font-semibold tracking-tight">
            <HeartPulse className="h-5 w-5 text-primary" />
            SafeHaven AI
          </Link>
          {user && (
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
              <Link to="/medication-verification">
                <Button variant="ghost" size="sm">
                  <ScanLine className="h-4 w-4" />
                  Medication Verification
                </Button>
              </Link>
              <span>{user.full_name}</span>
              <Button variant="ghost" size="sm" onClick={handleLogout}>
                <LogOut className="h-4 w-4" />
                Log out
              </Button>
            </div>
          )}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  )
}
