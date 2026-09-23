import { HeartPulse, LogOut, ScanLine, ShieldAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useAlertNotifications } from '@/features/safety-monitoring/use-alert-notifications'
import { useLiveSafetyAlerts } from '@/features/safety-monitoring/use-safety-alerts'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

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
              <SafetyMonitoringNavItem />
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

/**
 * Live alert count in the header, plus the global notifier.
 *
 * Both live here rather than on the alerts page so a nurse is told about a
 * possible fall wherever they are in the app — an alert only visible on the
 * page you are already looking at is close to no alert at all
 * (DOCUMENTATION.md §13).
 *
 * Shares a query key with the alerts page, so react-query serves both from a
 * single poll rather than two. Rendered only for a signed-in clinician, so the
 * public /care route and the login page never poll.
 */
function SafetyMonitoringNavItem() {
  useAlertNotifications()
  const { data } = useLiveSafetyAlerts()

  const alerts = data?.results ?? []
  const highCount = alerts.filter((a) => a.priority === 'HIGH').length

  return (
    <Link to="/safety-monitoring">
      <Button variant="ghost" size="sm" data-testid="safety-monitoring-nav">
        <ShieldAlert className={cn('h-4 w-4', highCount > 0 && 'text-red-600')} />
        Safety Monitoring
        {alerts.length > 0 && (
          <span
            className={cn(
              'ml-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-xs font-semibold',
              // Red only when something is genuinely urgent. A permanently red
              // badge stops meaning anything.
              highCount > 0 ? 'bg-red-600 text-white' : 'bg-muted-foreground/20 text-foreground',
            )}
            data-testid="safety-alert-count"
          >
            {alerts.length}
          </span>
        )}
      </Button>
    </Link>
  )
}
