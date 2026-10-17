// SafeHaven patient app service worker: dose reminders only. It caches
// nothing and never touches page requests, so the staff dashboard on the
// same site behaves exactly as before.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const title = data.title || 'SafeHaven'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || 'Open SafeHaven to see your medicines.',
      icon: '/app/icon-192.png',
      badge: '/app/badge-96.png',
      tag: data.tag || 'safehaven',
      renotify: true,
      data: { url: data.url || '/my' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/my'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if (new URL(client.url).pathname.startsWith('/my') && 'focus' in client) {
          client.navigate(url)
          return client.focus()
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
