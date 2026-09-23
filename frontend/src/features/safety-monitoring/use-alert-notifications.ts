import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { useAlertSound } from '@/features/safety-monitoring/use-alert-sound'
import { useLiveSafetyAlerts } from '@/features/safety-monitoring/use-safety-alerts'
import type { SafetyAlert } from '@/types/safety-monitoring'

/**
 * Watches the live alert queue and announces genuinely new alerts.
 *
 * Mounted once in AppLayout so a nurse is notified wherever they are in the
 * app, not only on the alerts page.
 *
 * Two behaviours matter more than they look:
 *
 * 1. The first successful poll SEEDS the seen-set without announcing anything.
 *    Otherwise every page load, every login and every tab reopen would replay
 *    every open alert as if it had just happened — which is both alarming and
 *    exactly the "alert that fires on correct work" failure DOCUMENTATION.md
 *    §7 rule 6 warns about.
 *
 * 2. LOW-priority alerts are never announced. A low battery belongs in the
 *    queue, not interrupting a nurse mid-task. Announcing everything is how a
 *    channel gets muted, and then a real fall goes unheard.
 */
export function useAlertNotifications() {
  const { data } = useLiveSafetyAlerts()
  const { play } = useAlertSound()

  const seenIds = useRef<Set<string> | null>(null)

  useEffect(() => {
    if (!data) return
    const alerts = data.results

    // First load: remember what already exists, announce none of it.
    if (seenIds.current === null) {
      seenIds.current = new Set(alerts.map((a) => a.id))
      return
    }

    const fresh = alerts.filter((a) => !seenIds.current!.has(a.id))
    for (const alert of fresh) seenIds.current.add(alert.id)

    const announceable = fresh.filter((a) => a.priority !== 'LOW')
    if (announceable.length === 0) return

    for (const alert of announceable) announce(alert)

    // One sound for the batch, however many arrived — a burst of chimes would
    // be its own kind of alarm fatigue.
    if (announceable.some((a) => a.priority === 'HIGH')) play()
  }, [data, play])
}

function announce(alert: SafetyAlert) {
  const where = alert.room_number ? `Room ${alert.room_number}` : 'Room not recorded'
  const description = `${alert.patient_name} (${alert.patient_code}) · ${where} · ${alert.device_code}`

  // `alert.message` is rendered by the backend from a single table, so the
  // observed-not-diagnosed wording is identical here, on the card, and in the
  // audit timeline. Never compose alert text in the UI.
  if (alert.priority === 'HIGH') {
    toast.error(alert.message, { description, duration: 15_000 })
  } else {
    toast.warning(alert.message, { description, duration: 8_000 })
  }
}
