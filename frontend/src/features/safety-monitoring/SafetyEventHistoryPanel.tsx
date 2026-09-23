import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { Activity, BatteryLow, ClockAlert, Footprints, PersonStanding } from 'lucide-react'

import { listPatientSafetyEvents } from '@/api/safety-monitoring'
import { Skeleton } from '@/components/ui/skeleton'
import type { SensorEvent, SensorEventType } from '@/types/safety-monitoring'

const EVENT_ICONS: Record<SensorEventType, typeof Activity> = {
  POSSIBLE_FALL: PersonStanding,
  ABNORMAL_MOVEMENT: Activity,
  UNEXPECTED_MOBILITY: Footprints,
  DEVICE_LOW_BATTERY: BatteryLow,
}

// Same observed-not-diagnosed wording rule as everywhere else. These describe
// what the sensor measured, never what caused it.
const EVENT_LABELS: Record<SensorEventType, string> = {
  POSSIBLE_FALL: 'Possible fall',
  ABNORMAL_MOVEMENT: 'Abnormal repetitive movement',
  UNEXPECTED_MOBILITY: 'Unexpected mobility',
  DEVICE_LOW_BATTERY: 'Low battery',
}

/**
 * Everything the wearable reported for this patient, newest first.
 *
 * Distinct from the alert queue on purpose. The queue shows episodes needing
 * action; this shows raw observations — including the ones that deliberately
 * did NOT raise an alert. That difference is the point: being able to see that
 * a weak impact was recorded and correctly suppressed is how you build trust
 * that the silence means something.
 */
export function SafetyEventHistoryPanel({ patientId }: { patientId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['patient-safety-events', patientId],
    queryFn: () => listPatientSafetyEvents(patientId),
  })

  if (isLoading) return <Skeleton className="h-24 w-full" />
  if (isError) return <p className="text-sm text-muted-foreground">Could not load safety events.</p>
  if (!data || data.total === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="no-safety-events">
        No wearable events recorded for this patient.
      </p>
    )
  }

  return (
    <div className="space-y-2" data-testid="safety-event-history">
      <p className="text-xs text-muted-foreground">
        Everything the wearable reported, including events that did not raise an alert.
      </p>
      {data.results.map((event) => (
        <EventRow key={event.id} event={event} />
      ))}
    </div>
  )
}

function EventRow({ event }: { event: SensorEvent }) {
  const Icon = EVENT_ICONS[event.event_type]
  const score = event.metrics['fall_score']
  const stages = event.metrics['stages_seen']

  return (
    <div
      className="flex items-start justify-between gap-4 rounded-lg border px-3 py-2"
      data-testid="safety-event-row"
      data-event-type={event.event_type}
    >
      <div className="flex min-w-0 gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{EVENT_LABELS[event.event_type]}</p>
          <p className="text-xs text-muted-foreground">
            {format(new Date(event.occurred_at), 'd MMM yyyy, HH:mm:ss')}
            {/* The evidence behind the event, so a reviewer can see WHY rather
                than trusting a label. This is the Module 3 analogue of Module
                2's per-check detail. */}
            {typeof score === 'number' && score > 0 && ` · score ${score}/4`}
            {Array.isArray(stages) && stages.length > 0 && ` · ${stages.join(', ')}`}
          </p>
        </div>
      </div>

      {event.delayed && (
        <span
          className="flex shrink-0 items-center gap-1 text-xs font-medium text-amber-700 dark:text-amber-400"
          data-testid="safety-event-delayed"
          title={`Detected ${format(new Date(event.occurred_at), 'HH:mm:ss')}, received ${format(new Date(event.received_at), 'HH:mm:ss')}`}
        >
          <ClockAlert className="h-3 w-3" />
          Delayed
        </span>
      )}
    </div>
  )
}
