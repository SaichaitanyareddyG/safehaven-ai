import { useMutation, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import {
  Activity,
  BatteryLow,
  Check,
  ClockAlert,
  Footprints,
  PersonStanding,
  WifiOff,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { acknowledgeSafetyAlert, resolveSafetyAlert } from '@/api/safety-monitoring'
import { Button } from '@/components/ui/button'
import { AlertPriorityBadge, AlertStatusBadge } from '@/features/safety-monitoring/AlertBadges'
import { SAFETY_ALERTS_QUERY_KEY } from '@/features/safety-monitoring/use-safety-alerts'
import { cn } from '@/lib/utils'
import type { AlertType, SafetyAlert } from '@/types/safety-monitoring'

const ALERT_ICONS: Record<AlertType, typeof Activity> = {
  POSSIBLE_FALL: PersonStanding,
  ABNORMAL_MOVEMENT: Activity,
  UNEXPECTED_MOBILITY: Footprints,
  DEVICE_LOW_BATTERY: BatteryLow,
  DEVICE_OFFLINE: WifiOff,
}

// Left border only, so the card reads as urgent at a glance without a wall of
// colour. HIGH is the only one that gets a filled tint.
const CARD_ACCENT: Record<string, string> = {
  HIGH: 'border-l-4 border-l-red-500 bg-red-50/40 dark:bg-red-950/20',
  MEDIUM: 'border-l-4 border-l-amber-500',
  LOW: 'border-l-4 border-l-muted-foreground/30',
}

export function SafetyAlertCard({ alert }: { alert: SafetyAlert }) {
  const queryClient = useQueryClient()
  const Icon = ALERT_ICONS[alert.alert_type]

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: SAFETY_ALERTS_QUERY_KEY })
  }

  const acknowledge = useMutation({
    mutationFn: () => acknowledgeSafetyAlert(alert.id),
    onSuccess: invalidate,
    onError: (error: Error) => toast.error(error.message),
  })

  const resolve = useMutation({
    mutationFn: () => resolveSafetyAlert(alert.id),
    onSuccess: () => {
      invalidate()
      toast.success('Alert resolved')
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const busy = acknowledge.isPending || resolve.isPending

  return (
    <div
      className={cn('rounded-lg border bg-background p-4', CARD_ACCENT[alert.priority])}
      data-testid="safety-alert-card"
      data-alert-type={alert.alert_type}
      data-priority={alert.priority}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 gap-3">
          <Icon
            className={cn(
              'mt-0.5 h-5 w-5 shrink-0',
              alert.priority === 'HIGH' ? 'text-red-600' : 'text-muted-foreground',
            )}
          />
          <div className="min-w-0">
            {/* Server-rendered wording. Never composed here, so the
                observed-not-diagnosed phrasing cannot drift between surfaces. */}
            <p className="font-medium leading-snug" data-testid="safety-alert-message">
              {alert.message}
            </p>

            <p className="mt-1 text-sm text-muted-foreground">
              <Link
                to={`/patients/${alert.patient_id}`}
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                {alert.patient_name}
              </Link>{' '}
              ({alert.patient_code})
              {alert.room_number ? ` · Room ${alert.room_number}` : ' · Room not recorded'} ·{' '}
              {alert.device_code}
            </p>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <AlertPriorityBadge priority={alert.priority} />
              <AlertStatusBadge status={alert.status} />
              <span>{formatDistanceToNow(new Date(alert.created_at), { addSuffix: true })}</span>
              {/* One alert is one episode. Showing the fold count keeps the
                  deduplication visible instead of looking like lost data. */}
              {alert.event_count > 1 && (
                <span data-testid="alert-event-count">{alert.event_count} events</span>
              )}
              {alert.delayed && (
                <span
                  className="inline-flex items-center gap-1 font-medium text-amber-700 dark:text-amber-400"
                  data-testid="alert-delayed"
                  title="This event was queued during a network outage and delivered late."
                >
                  <ClockAlert className="h-3 w-3" />
                  Delayed delivery — detected earlier than shown
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 gap-2">
          <Button asChild variant="outline" size="sm">
            <Link to={`/patients/${alert.patient_id}`}>View patient</Link>
          </Button>
          {alert.status === 'OPEN' && (
            <Button
              size="sm"
              disabled={busy}
              onClick={() => acknowledge.mutate()}
              data-testid="acknowledge-alert"
            >
              <Check className="h-4 w-4" />
              Acknowledge
            </Button>
          )}
          {/* Resolving straight from OPEN is allowed — requiring an
              acknowledge first would add a click with no safety value. Hidden
              once resolved: offering an action that does nothing invites a
              nurse to wonder whether the first click registered. */}
          {alert.status !== 'RESOLVED' && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => resolve.mutate()}
              data-testid="resolve-alert"
            >
              Resolve
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
