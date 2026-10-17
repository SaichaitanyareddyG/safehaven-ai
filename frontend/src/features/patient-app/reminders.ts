import { removePushSubscription, savePushSubscription } from '@/api/patient-app'

/** Where this phone stands with dose reminders. */
export type ReminderState =
  | 'unsupported' // this browser cannot show reminders
  | 'install-first' // iPhone/iPad: works only from the Home Screen app
  | 'denied' // the person blocked notifications for this site
  | 'off'
  | 'on'

function isIos(): boolean {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  )
}

export async function reminderState(): Promise<ReminderState> {
  const supported = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  if (!supported) return isIos() && !isStandalone() ? 'install-first' : 'unsupported'
  if (Notification.permission === 'denied') return 'denied'
  const registration = await navigator.serviceWorker.getRegistration('/')
  const subscription = await registration?.pushManager.getSubscription()
  return subscription && Notification.permission === 'granted' ? 'on' : 'off'
}

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + '='.repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

/** Must run from a tap: browsers only ask for permission after one. */
export async function turnOnReminders(publicKey: string): Promise<ReminderState> {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off'
  const registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
  await navigator.serviceWorker.ready
  const subscription =
    (await registration.pushManager.getSubscription()) ??
    (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(publicKey) }))
  await savePushSubscription(subscription.toJSON())
  return 'on'
}

/** Also used at sign-out: the next person on this phone gets none of these. */
export async function turnOffReminders(): Promise<void> {
  if (!('serviceWorker' in navigator)) return
  const registration = await navigator.serviceWorker.getRegistration('/')
  const subscription = await registration?.pushManager.getSubscription()
  if (!subscription) return
  try {
    await removePushSubscription(subscription.endpoint)
  } catch {
    // Signed out already, or offline: the browser side below still stops them.
  }
  await subscription.unsubscribe()
}
