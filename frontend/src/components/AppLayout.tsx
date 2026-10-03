import {
  Bell,
  ChevronUp,
  KeyRound,
  LogOut,
  Compass,
  Menu,
  QrCode,
  ScanLine,
  ShieldCheck,
  Users,
  Watch,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import { Logo } from '@/components/BrandPanel'
import { GuidedTour } from '@/components/GuidedTour'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAlertNotifications } from '@/features/safety-monitoring/use-alert-notifications'
import { useLiveSafetyAlerts } from '@/features/safety-monitoring/use-safety-alerts'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  /** Anchor for the guided tour (see GuidedTour's steps). */
  tour: string
  testId?: string
}

const WARD_ITEMS: NavItem[] = [
  { to: '/patients', label: 'Patients', icon: Users, tour: 'patients', testId: 'patients-nav' },
  { to: '/devices', label: 'Bands', icon: Watch, tour: 'devices', testId: 'devices-nav' },
  { to: '/scan-band', label: 'Scan band', icon: QrCode, tour: 'scan-band', testId: 'scan-band-nav' },
  { to: '/medication-verification', label: 'Medication check', icon: ScanLine, tour: 'medication' },
]

const ADMIN_ITEMS: NavItem[] = [
  { to: '/admin/users', label: 'Users', icon: ShieldCheck, tour: 'users', testId: 'users-nav' },
]

/**
 * The signed-in dashboard: a dark teal side menu (the brand of the sign-in
 * screen) and the page beside it. On a phone the menu folds into a top bar
 * with a menu button. Design: the "SafeHaven Dashboard Navigation" canvas.
 */
export function AppLayout({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [menuOpen, setMenuOpen] = useState(false)
  const [tourRequested, setTourRequested] = useState(false)
  const [tourDismissed, setTourDismissed] = useState(false)
  // A new user's first visit shows the tour once; anyone can replay it.
  const touring = tourRequested || (!!user && !user.tour_completed && !tourDismissed)

  return (
    <div className="min-h-screen bg-[#F3F7F8] lg:flex">
      {/* Phone top bar */}
      <div className="sticky top-0 z-30 flex h-16 items-center gap-2.5 bg-[#143440] pr-2 pl-4 lg:hidden">
        <Logo className="h-6.5 w-6.5" />
        <span className="text-[15px] font-semibold tracking-[0.2em] text-[#7CC3DB]">SAFEHAVEN AI</span>
        <button
          type="button"
          onClick={() => setMenuOpen((v) => !v)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          aria-expanded={menuOpen}
          aria-controls="side-nav"
          className="ml-auto flex h-12 w-12 items-center justify-center rounded-xl text-[#E6F0F3] hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-[#4F93AD]/50 focus-visible:outline-none"
        >
          {menuOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>

      {user && (
        <SideNav
          open={menuOpen}
          onNavigate={() => setMenuOpen(false)}
          onStartTour={() => {
            setMenuOpen(false)
            setTourRequested(true)
          }}
        />
      )}

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-6xl px-4 py-8 lg:px-10 lg:py-10">{children}</div>
      </main>

      {touring && (
        <GuidedTour
          onClose={() => {
            setTourRequested(false)
            setTourDismissed(true)
          }}
        />
      )}
    </div>
  )
}

function SideNav({
  open,
  onNavigate,
  onStartTour,
}: {
  open: boolean
  onNavigate: () => void
  onStartTour: () => void
}) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  return (
    <nav
      id="side-nav"
      aria-label="Main"
      // Following a link closes the phone menu.
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('a')) onNavigate()
      }}
      className={cn(
        'z-20 flex-col gap-6 bg-[#143440] px-3.5 py-6 text-[#E6F0F3]',
        // Phone: a full-height sheet under the top bar. Desktop: a fixed column.
        open ? 'fixed inset-x-0 top-16 bottom-0 flex overflow-y-auto' : 'hidden',
        'lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-66 lg:shrink-0',
      )}
    >
      <div className="hidden items-center gap-2.5 px-2.5 lg:flex">
        <Logo className="h-7.5 w-7.5" />
        <span className="text-base font-semibold tracking-[0.2em] text-[#7CC3DB]">SAFEHAVEN AI</span>
      </div>

      <NavSection title="Ward">
        <AlertsNavItem />
        {WARD_ITEMS.map((item) => (
          <NavItemLink key={item.to} item={item} />
        ))}
      </NavSection>

      {isAdmin && (
        <NavSection title="Admin">
          {ADMIN_ITEMS.map((item) => (
            <NavItemLink key={item.to} item={item} />
          ))}
        </NavSection>
      )}

      <UserMenu onStartTour={onStartTour} />
    </nav>
  )
}

function NavSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="px-3 pb-1.5 text-xs font-semibold tracking-[0.12em] text-[#9FB9C3] uppercase">{title}</span>
      {children}
    </div>
  )
}

const linkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex min-h-12 items-center gap-3 rounded-[10px] px-3 text-[15px] font-medium transition-colors lg:min-h-[46px]',
    'focus-visible:ring-3 focus-visible:ring-[#4F93AD]/50 focus-visible:outline-none',
    isActive ? 'bg-[#1F4B5A] text-white' : 'text-[#E6F0F3] hover:bg-white/6',
  )

function NavItemLink({ item }: { item: NavItem }) {
  const Icon = item.icon
  return (
    <NavLink to={item.to} className={linkClass} data-testid={item.testId} data-tour={item.tour}>
      {({ isActive }) => (
        <>
          <Icon className={cn('h-5 w-5', isActive ? 'text-[#7CC3DB]' : 'text-[#9FB9C3]')} aria-hidden="true" />
          {item.label}
        </>
      )}
    </NavLink>
  )
}

/**
 * Safety alerts, with the live count, plus the global notifier.
 *
 * Both live in the menu rather than on the alerts page so a nurse is told
 * about a possible fall wherever they are in the app — an alert only visible
 * on the page you are already looking at is close to no alert at all
 * (DOCUMENTATION.md §13).
 *
 * Shares a query key with the alerts page, so react-query serves both from a
 * single poll rather than two. Rendered only for a signed-in clinician, so the
 * public /care route and the login page never poll.
 */
function AlertsNavItem() {
  useAlertNotifications()
  const { data } = useLiveSafetyAlerts()

  const alerts = data?.results ?? []
  const highCount = alerts.filter((a) => a.priority === 'HIGH').length

  return (
    <NavLink to="/safety-monitoring" className={linkClass} data-testid="safety-monitoring-nav" data-tour="alerts">
      {({ isActive }) => (
        <>
          <Bell className={cn('h-5 w-5', isActive ? 'text-[#7CC3DB]' : 'text-[#9FB9C3]')} aria-hidden="true" />
          Safety alerts
          {alerts.length > 0 && (
            <span
              className={cn(
                'ml-auto inline-flex h-6 min-w-6 items-center justify-center rounded-full px-2 text-[13px] font-semibold',
                // Loud only when something is genuinely urgent. A permanently
                // loud badge stops meaning anything.
                highCount > 0 ? 'bg-[#F59E3D] text-[#241200]' : 'bg-white/15 text-white',
              )}
              data-testid="safety-alert-count"
              aria-label={`${alerts.length} open alert${alerts.length === 1 ? '' : 's'}`}
            >
              {alerts.length}
            </span>
          )}
        </>
      )}
    </NavLink>
  )
}

function UserMenu({ onStartTour }: { onStartTour: () => void }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  if (!user) return null

  return (
    <div className="mt-auto border-t border-[#24505F] pt-4" data-tour="user-menu">
      <DropdownMenu>
        <DropdownMenuTrigger
          className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-white/6 focus-visible:ring-3 focus-visible:ring-[#4F93AD]/50 focus-visible:outline-none"
          data-testid="user-menu"
        >
          <span
            aria-hidden="true"
            className="flex h-9.5 w-9.5 shrink-0 items-center justify-center rounded-full bg-[#1F4B5A] text-[15px] font-semibold text-[#E6F0F3]"
          >
            {user.full_name.trim().charAt(0).toUpperCase()}
          </span>
          <span className="flex min-w-0 flex-col">
            <span className="truncate text-[15px] font-medium text-[#F2F7F9]">{user.full_name}</span>
            <span className="text-[13px] text-[#9FB9C3]">{user.role === 'admin' ? 'Admin' : 'Clinician'}</span>
          </span>
          <ChevronUp className="ml-auto h-4 w-4 text-[#9FB9C3]" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-56">
          <DropdownMenuItem onSelect={onStartTour}>
            <Compass className="h-4 w-4" />
            Take the tour
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => navigate('/change-password')}>
            <KeyRound className="h-4 w-4" />
            Change password
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            data-testid="logout"
            onSelect={() => {
              logout()
              navigate('/login')
            }}
          >
            <LogOut className="h-4 w-4" />
            Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
