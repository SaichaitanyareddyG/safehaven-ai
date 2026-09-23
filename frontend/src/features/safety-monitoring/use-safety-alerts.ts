import { useQuery } from '@tanstack/react-query'

import { listSafetyAlerts } from '@/api/safety-monitoring'

/**
 * Shared query key. The alerts page and the header badge both use it, so
 * react-query serves both from ONE poll rather than two.
 */
export const SAFETY_ALERTS_QUERY_KEY = ['safety-alerts', 'live'] as const

/**
 * Poll interval for the nurse alert queue.
 *
 * Polling rather than WebSocket/SSE is a deliberate architectural decision
 * (MODULE_3_IMPLEMENTATION_PLAN.md §21, decision D1), and the reason is
 * deployment rather than elegance: any in-process push broadcasts from a
 * single worker's memory, so running uvicorn with `--workers 2` would mean a
 * nurse connected to worker A silently never receives an alert ingested by
 * worker B. Fixing that needs Redis pub/sub — a dependency and a service this
 * project does not have. Polling reads Postgres, so it is correct under any
 * worker count. A real-time mechanism that silently drops patient-safety
 * alerts under a standard deployment flag is worse than a three-second poll.
 *
 * 3s comfortably meets the "within a few seconds" requirement; the query is a
 * single indexed read on (status, created_at).
 */
export const ALERT_POLL_INTERVAL_MS = 3_000

export function useLiveSafetyAlerts() {
  return useQuery({
    queryKey: SAFETY_ALERTS_QUERY_KEY,
    queryFn: () => listSafetyAlerts(),
    refetchInterval: ALERT_POLL_INTERVAL_MS,
    // Override the global 10s staleTime: for a safety queue, cached-and-stale
    // is the wrong default.
    staleTime: 0,
    // Deliberately NOT refetchIntervalInBackground. A hidden tab polling every
    // three seconds is pure waste, and react-query refetches on window focus
    // anyway, so returning to the tab shows current data immediately.
  })
}
