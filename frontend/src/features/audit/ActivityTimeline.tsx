import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Info, User } from 'lucide-react'

import { listPatientAuditEvents } from '@/api/audit'
import { Skeleton } from '@/components/ui/skeleton'
import { auditEventCategory, auditEventDescription } from '@/lib/audit-event-labels'
import { cn } from '@/lib/utils'
import type { AuditEvent } from '@/types/audit'

const CATEGORY_STYLES: Record<string, { dot: string; icon: typeof Info }> = {
  info: { dot: 'bg-muted-foreground/40', icon: Info },
  'safety-warning': { dot: 'bg-destructive', icon: AlertTriangle },
  approval: { dot: 'bg-green-600', icon: CheckCircle2 },
  'patient-activity': { dot: 'bg-blue-500', icon: User },
}

function TimelineRow({ event }: { event: AuditEvent }) {
  const category = auditEventCategory(event.event_type)
  const style = CATEGORY_STYLES[category]
  const Icon = style.icon
  const isWarning = category === 'safety-warning'

  return (
    <li className="flex gap-3" data-testid="timeline-row" data-event-type={event.event_type}>
      <div className="flex flex-col items-center">
        <span className={cn('flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-white', style.dot)}>
          <Icon className="h-3.5 w-3.5" />
        </span>
        <span className="mt-1 w-px flex-1 bg-border" />
      </div>
      <div className="pb-4">
        <p className={cn('text-sm font-medium', isWarning && 'text-destructive')}>{auditEventDescription(event)}</p>
        <p className="text-xs text-muted-foreground">
          {new Date(event.created_at).toLocaleString()} · {event.actor_type.charAt(0) + event.actor_type.slice(1).toLowerCase()}
        </p>
      </div>
    </li>
  )
}

export function ActivityTimeline({ patientId }: { patientId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['patient-audit', patientId],
    queryFn: () => listPatientAuditEvents(patientId),
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-6 w-full" />
      </div>
    )
  }

  if (isError || !data) {
    return <p className="text-sm text-destructive">Failed to load activity timeline.</p>
  }

  if (data.results.length === 0) {
    return <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
  }

  return (
    <ul className="mt-2">
      {data.results.map((event) => (
        <TimelineRow key={event.id} event={event} />
      ))}
    </ul>
  )
}
