import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { useAlertSound } from '@/features/safety-monitoring/use-alert-sound'
import { showDesktopAlert } from '@/features/safety-monitoring/use-desktop-notifications'
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
const APP_TITLE = 'SAFEHAVEN'

export function useAlertNotifications() {
  const { data } = useLiveSafetyAlerts()
  const { play, speak } = useAlertSound()

  // Priority is tracked per alert, not just the id. Tracking ids alone missed
  // ESCALATION: an ongoing episode promoted from MEDIUM to HIGH keeps the same
  // id, so it produced no toast and no sound — the alert silently became
  // urgent while nobody was told. See §3 of the edge-case review.
  const seen = useRef<Map<string, SafetyAlert['priority']> | null>(null)

  // Open, non-LOW alerts in the tab title, so the count is visible from any
  // other tab or window — the cheapest signal there is.
  useEffect(() => {
    const open = (data?.results ?? []).filter((a) => a.status === 'OPEN' && a.priority !== 'LOW')
    document.title = open.length > 0 ? `(${open.length}) Alert · ${APP_TITLE}` : APP_TITLE
  }, [data])
  useEffect(() => () => void (document.title = APP_TITLE), [])

  useEffect(() => {
    if (!data) return
    const alerts = data.results

    // First load: remember what already exists, announce none of it.
    if (seen.current === null) {
      seen.current = new Map(alerts.map((a) => [a.id, a.priority]))
      return
    }

    const announceable: SafetyAlert[] = []
    for (const alert of alerts) {
      const previous = seen.current.get(alert.id)
      const isNew = previous === undefined
      // Only upward moves count. A de-escalation is not news, and the backend
      // never downgrades anyway.
      const escalatedToHigh = !isNew && previous !== 'HIGH' && alert.priority === 'HIGH'

      seen.current.set(alert.id, alert.priority)

      if (alert.priority === 'LOW') continue
      if (isNew || escalatedToHigh) announceable.push(alert)
    }

    if (announceable.length === 0) return
    for (const alert of announceable) announce(alert)

    // One sound for the batch, however many arrived — a burst of chimes would
    // be its own kind of alarm fatigue.
    if (announceable.some((a) => a.priority === 'HIGH')) play()

    // Then say what happened and where, e.g. "Possible fall detected, check
    // patient. Room 12." Room only, never the name — a ward can hear it. At
    // most two read in full; a burst is summarised, not recited.
    const spoken = announceable.slice(0, 2).map(spokenLine)
    if (announceable.length > 2) spoken.push(`And ${announceable.length - 2} more alerts.`)
    speak(spoken)
  }, [data, play, speak])
}

function spokenLine(alert: SafetyAlert): string {
  const where = alert.room_number ? ` Room ${alert.room_number}.` : ''
  return `${alert.message.replace(/\s*—\s*/g, ', ')}${where}`
}

function announce(alert: SafetyAlert) {
  const where = alert.room_number ? `Room ${alert.room_number}` : 'Room not recorded'
  const description = `${alert.patient_name} (${alert.patient_code}) · ${where} · ${alert.device_code}`

  // `alert.message` is rendered by the backend from a single table, so the
  // observed-not-diagnosed wording is identical here, on the card, and in the
  // audit timeline. Never compose alert text in the UI.
  // Red for urgent (fall, help, no response), amber otherwise; one tap to
  // the patient. A full page load is fine here: this runs outside React.
  const viewPatient = {
    label: 'View patient',
    onClick: () => window.location.assign(`/patients/${alert.patient_id}`),
  }
  if (alert.priority === 'HIGH') {
    toast.error(alert.message, { description, duration: 30_000, action: viewPatient })
  } else {
    toast.warning(alert.message, { description, duration: 10_000, action: viewPatient })
  }

  // Hidden tab: also an OS notification. Patient code and room only — see
  // showDesktopAlert for why the name is left out.
  showDesktopAlert(alert.id, alert.message, `${alert.patient_code} · ${where}`, alert.priority === 'HIGH')
}
