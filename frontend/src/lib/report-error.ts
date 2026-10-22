// Tells the server a page broke (kind of error and which page only — no
// message text, which can contain what was on screen). See
// backend/app/core/client_errors.py. At most a few per page load.

let reported = 0

function appFor(path: string): 'staff' | 'patient' | 'care-link' {
  if (path.startsWith('/my')) return 'patient'
  if (path.startsWith('/care')) return 'care-link'
  return 'staff'
}

export function reportError(error: unknown): void {
  if (reported >= 3) return
  reported += 1
  const name = error instanceof Error ? error.name : 'Error'
  const path = window.location.pathname
  try {
    void fetch(new URL('/client-errors', import.meta.env.VITE_API_BASE_URL), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app: appFor(path), path, error_type: name }),
      keepalive: true,
    }).catch(() => undefined)
  } catch {
    // Reporting must never cause a second error.
  }
}

export function reportUncaughtErrors(): void {
  window.addEventListener('error', (event) => reportError(event.error))
  window.addEventListener('unhandledrejection', (event) => reportError(event.reason))
}
