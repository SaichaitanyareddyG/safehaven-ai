import { useQuery } from '@tanstack/react-query'
import { BellRing, ShieldCheck, Volume2, VolumeX } from 'lucide-react'

import { listSafetyAlerts } from '@/api/safety-monitoring'
import { AppLayout } from '@/components/AppLayout'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { SafetyAlertCard } from '@/features/safety-monitoring/SafetyAlertCard'
import { useAlertSound } from '@/features/safety-monitoring/use-alert-sound'
import {
  ALERT_POLL_INTERVAL_MS,
  useLiveSafetyAlerts,
} from '@/features/safety-monitoring/use-safety-alerts'

/**
 * The cross-patient alert queue.
 *
 * DOCUMENTATION.md §13 calls the absence of this "the single biggest remaining
 * usability gap": until now every safety signal was only visible if someone
 * opened that specific patient, and nobody is watching every patient. An alert
 * nobody sees is close to an alert that did not fire.
 */
export function SafetyAlertsPage() {
  const { data, isLoading, isError, error, dataUpdatedAt } = useLiveSafetyAlerts()
  const sound = useAlertSound()

  // Recently resolved, shown separately and collapsed to the last few. Kept
  // off the main list on purpose: a queue that mixes live and closed alerts
  // buries the ones needing action.
  const { data: resolved } = useQuery({
    queryKey: ['safety-alerts', 'resolved'],
    queryFn: () => listSafetyAlerts(['RESOLVED']),
    staleTime: 30_000,
  })

  const alerts = data?.results ?? []
  const highCount = alerts.filter((a) => a.priority === 'HIGH').length

  return (
    <AppLayout>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Safety Monitoring</h1>
          <p className="text-sm text-muted-foreground">
            Wearable alerts across every monitored patient. Updates every{' '}
            {ALERT_POLL_INTERVAL_MS / 1000} seconds.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={sound.toggle}
          data-testid="toggle-alert-sound"
          title={
            sound.enabled
              ? 'Audible alerts are on for high-priority alerts'
              : 'Audible alerts are off — alerts will still appear on screen'
          }
        >
          {sound.enabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
          {sound.enabled ? 'Sound on' : 'Sound off'}
        </Button>
      </div>

      {isError && (
        <Alert variant="destructive" className="mb-4">
          <AlertTitle>Could not load alerts</AlertTitle>
          <AlertDescription>
            {error instanceof Error ? error.message : 'Unknown error'}. Monitoring is still
            running; this page will keep retrying.
          </AlertDescription>
        </Alert>
      )}

      {isLoading && (
        <div className="space-y-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      )}

      {!isLoading && alerts.length === 0 && (
        <div
          className="rounded-lg border border-dashed bg-background p-10 text-center"
          data-testid="no-alerts"
        >
          <ShieldCheck className="mx-auto h-8 w-8 text-emerald-600" />
          <p className="mt-3 font-medium">No active safety alerts</p>
          {/* Saying monitoring is still running matters: silence should read
              as "nothing to report", not as "is this thing on?". */}
          <p className="mt-1 text-sm text-muted-foreground">
            Monitoring is active. Alerts appear here automatically.
          </p>
        </div>
      )}

      {alerts.length > 0 && (
        <>
          <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
            <BellRing className="h-4 w-4" />
            <span data-testid="alert-summary">
              {alerts.length} active {alerts.length === 1 ? 'alert' : 'alerts'}
              {highCount > 0 && ` · ${highCount} high priority`}
            </span>
            {dataUpdatedAt > 0 && (
              <span className="ml-auto text-xs">
                Updated {new Date(dataUpdatedAt).toLocaleTimeString()}
              </span>
            )}
          </div>

          <div className="space-y-3">
            {alerts.map((alert) => (
              <SafetyAlertCard key={alert.id} alert={alert} />
            ))}
          </div>
        </>
      )}

      {resolved && resolved.total > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-sm font-medium text-muted-foreground">Recently resolved</h2>
          <div className="space-y-3 opacity-70">
            {resolved.results.slice(0, 5).map((alert) => (
              <SafetyAlertCard key={alert.id} alert={alert} />
            ))}
          </div>
        </section>
      )}
    </AppLayout>
  )
}
