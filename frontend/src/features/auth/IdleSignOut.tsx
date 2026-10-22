import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useAuth } from '@/lib/auth-context'

// HIPAA's automatic logoff (45 CFR 164.312(a)(2)(iii)): a ward computer left
// signed in must not keep showing patient records. 15 minutes is the usual
// hospital setting; a warning gives the last minute to stay.
export const IDLE_LIMIT_MS = 15 * 60 * 1000
const WARNING_MS = 60 * 1000
// Shared by every tab, so working in one tab keeps the others signed in too.
const LAST_ACTIVE_KEY = 'safehaven.last_active'
export const IDLE_NOTE_KEY = 'safehaven.signed_out_idle'
// The Safety alerts screen is a ward monitor: it must keep showing new falls
// to whoever walks past, so it never signs itself out.
const MONITOR_PATHS = ['/safety-monitoring']

function readLastActive(): number {
  try {
    return Number(localStorage.getItem(LAST_ACTIVE_KEY)) || Date.now()
  } catch {
    return Date.now()
  }
}

function markActive() {
  try {
    localStorage.setItem(LAST_ACTIVE_KEY, String(Date.now()))
  } catch {
    // Private mode: this tab still times out on its own clock below.
  }
}

/** Signs staff out after 15 minutes without a click, key or scroll, with a
 *  one-minute warning. Lives in AppLayout, so it runs on every staff page. */
export function IdleSignOut() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null)
  const lastLocal = useRef(0)
  const onMonitor = MONITOR_PATHS.some((p) => pathname.startsWith(p))
  // Kept in refs so the effect below runs once per sign-in, not on every
  // render: background polling re-renders the page every few seconds and
  // must never count as the person being active.
  const signOutRef = useRef(() => {})
  useEffect(() => {
    signOutRef.current = () => {
      // A one-time note for the sign-in page, which says why. (Navigation
      // state is lost: the sign-in guard redirects as soon as the session
      // ends.)
      try {
        sessionStorage.setItem(IDLE_NOTE_KEY, '1')
      } catch {
        // No message then; the sign-out itself still happens.
      }
      logout()
      navigate('/login', { replace: true })
    }
  })
  const userId = user?.id

  useEffect(() => {
    if (!userId) return
    try {
      sessionStorage.removeItem(IDLE_NOTE_KEY)  // signed in again: the note has done its job
    } catch {
      // nothing to clear
    }
    lastLocal.current = Date.now()
    markActive()
    let lastWrite = 0
    const onActivity = () => {
      const now = Date.now()
      lastLocal.current = now
      // At most one storage write a second, however busy the mouse.
      if (now - lastWrite > 1000) {
        lastWrite = now
        markActive()
      }
    }
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart', 'scroll'] as const
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }))

    const timer = window.setInterval(() => {
      if (MONITOR_PATHS.some((p) => window.location.pathname.startsWith(p))) {
        markActive()
        setSecondsLeft(null)
        return
      }
      const idle = Date.now() - Math.max(readLastActive(), lastLocal.current)
      if (idle >= IDLE_LIMIT_MS) {
        signOutRef.current()
      } else if (idle >= IDLE_LIMIT_MS - WARNING_MS) {
        setSecondsLeft(Math.ceil((IDLE_LIMIT_MS - idle) / 1000))
      } else {
        setSecondsLeft(null)
      }
    }, 1000)

    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity))
      window.clearInterval(timer)
    }
  }, [userId])

  if (!user || onMonitor || secondsLeft === null) return null

  return (
    <Dialog open onOpenChange={(open) => !open && markActive()}>
      <DialogContent data-testid="idle-warning">
        <DialogHeader>
          <DialogTitle>Still there?</DialogTitle>
          <DialogDescription>
            For patient privacy you'll be signed out in {secondsLeft} second{secondsLeft === 1 ? '' : 's'}.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            onClick={() => {
              lastLocal.current = Date.now()
              markActive()
              setSecondsLeft(null)
            }}
            data-testid="idle-stay"
          >
            Stay signed in
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
