import { CalendarDays, ClipboardList, Home, LogOut, Pill } from 'lucide-react'
import type { ReactNode } from 'react'
import { Navigate, NavLink, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/BrandPanel'
import { turnOffReminders } from '@/features/patient-app/reminders'
import { usePatientAppHead } from '@/features/patient-app/use-my-data'
import { clearPatientToken, getPatientToken } from '@/lib/auth-storage'
import { queryClient } from '@/lib/query-client'
import { cn } from '@/lib/utils'

const TABS = [
  { to: '/my', label: 'Today', icon: Home, end: true },
  { to: '/my/medicines', label: 'Medicines', icon: Pill, end: false },
  { to: '/my/visits', label: 'Visits', icon: CalendarDays, end: false },
  { to: '/my/care', label: 'My care', icon: ClipboardList, end: false },
]

/** The patient app's frame: dark petrol header, big type, a bottom tab bar
 *  a thumb can reach. Signed-out visitors go to the sign-in page. */
export function MyAppLayout({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  const navigate = useNavigate()
  usePatientAppHead()
  if (!getPatientToken()) return <Navigate to="/my/sign-in" replace />

  async function signOut() {
    // Reminders stop on this phone before the session goes.
    await turnOffReminders().catch(() => undefined)
    clearPatientToken()
    // Nothing of this patient's stays in memory for the next person on this phone.
    queryClient.removeQueries({ queryKey: ['my'] })
    navigate('/my/sign-in', { replace: true })
  }

  return (
    <div className="min-h-dvh bg-[#F3F7F8] text-[#16252C]">
      <header className="bg-[#143440] text-[#E6F0F3]">
        <div className="mx-auto max-w-2xl px-5 pt-5 pb-6">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Logo className="h-6 w-6" />
              <span className="text-xs font-semibold tracking-[0.25em] text-[#7CC3DB]">SAFEHAVEN</span>
            </div>
            <button
              type="button"
              onClick={signOut}
              className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-[#B6C8CF] hover:bg-white/10 hover:text-white"
              data-testid="my-sign-out"
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </button>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-base text-[#9FB9C3]">{subtitle}</p>}
        </div>
      </header>

      {/* Bottom padding clears the fixed tab bar (and the iPhone home indicator). */}
      <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 pt-5 pb-[calc(6rem+env(safe-area-inset-bottom))]">
        {children}
      </main>

      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 border-t border-[#D3DFE4] bg-white pb-[env(safe-area-inset-bottom)]"
      >
        <div className="mx-auto grid max-w-2xl grid-cols-4 px-2 py-1.5">
          {TABS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  'flex min-h-14 flex-col items-center justify-center gap-1 rounded-lg text-[13px] font-medium',
                  isActive ? 'font-semibold text-[#0F6383]' : 'text-[#53656E] hover:text-[#16252C]',
                )
              }
            >
              <Icon className="h-6 w-6" aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}

/** A white rounded card, the app's one surface. */
export function MyCard({ children, className, ...rest }: React.ComponentProps<'div'>) {
  return (
    <div className={cn('rounded-2xl bg-white p-4 shadow-[0_1px_2px_rgba(22,37,44,0.06)]', className)} {...rest}>
      {children}
    </div>
  )
}

export function MySectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mt-2 text-lg font-semibold">{children}</h2>
}

export function MyLoading() {
  return <p className="py-8 text-center text-lg text-[#53656E]">Loading…</p>
}

export function MyLoadError() {
  return (
    <MyCard>
      <p className="text-lg">We couldn't load this just now. Check your connection and try again.</p>
    </MyCard>
  )
}
