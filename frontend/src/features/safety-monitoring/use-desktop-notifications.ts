import { useCallback, useState } from 'react'

/**
 * Operating-system notifications for safety alerts, so a fall is not silent
 * while the SAFEHAVEN tab is hidden behind other work.
 *
 * Permission can only be requested from a user gesture, so the alerts page
 * offers an explicit "Desktop alerts" button rather than prompting on load.
 */

export function desktopNotificationsSupported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

export function useDesktopNotificationPermission() {
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>(() =>
    desktopNotificationsSupported() ? Notification.permission : 'unsupported',
  )

  const request = useCallback(async () => {
    if (!desktopNotificationsSupported()) return
    setPermission(await Notification.requestPermission())
  }, [])

  return { permission, request }
}

/**
 * Show one alert as a system notification — only when the tab is hidden (when
 * it is visible the in-app toast already covers it) and only with permission.
 *
 * PRIVACY: the body carries the patient CODE and room, never the patient's
 * name. System notifications persist in the OS notification centre and can
 * appear on a locked screen, where a name is visible to anyone passing.
 */
export function showDesktopAlert(id: string, title: string, body: string, urgent: boolean) {
  if (!desktopNotificationsSupported() || Notification.permission !== 'granted') return
  if (!document.hidden) return
  const n = new Notification(title, { body, tag: id, requireInteraction: urgent })
  n.onclick = () => {
    window.focus()
    n.close()
  }
}
