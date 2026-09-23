import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { AlertPriority, AlertStatus, MonitoringProfile } from '@/types/safety-monitoring'

/**
 * Follows the app's established semantic palette (see components/StatusBadge):
 * emerald = good, amber = needs attention, destructive/red = critical,
 * muted = inert. Reusing it means a nurse does not have to learn a second
 * colour language for Module 3.
 */

const PRIORITY_STYLES: Record<AlertPriority, string> = {
  HIGH: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900',
  MEDIUM:
    'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  LOW: 'bg-muted text-muted-foreground border-border',
}

// "Priority" not "severity", everywhere it is shown. This is how soon someone
// should look, not a judgement about the patient's condition — Module 3 cannot
// make one.
const PRIORITY_LABEL: Record<AlertPriority, string> = {
  HIGH: 'High priority',
  MEDIUM: 'Medium priority',
  LOW: 'Low priority',
}

export function AlertPriorityBadge({ priority, className }: { priority: AlertPriority; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(PRIORITY_STYLES[priority], className)}
      data-testid="alert-priority-badge"
      data-priority={priority}
    >
      {PRIORITY_LABEL[priority]}
    </Badge>
  )
}

const STATUS_STYLES: Record<AlertStatus, string> = {
  OPEN: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900',
  ACKNOWLEDGED:
    'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900',
  RESOLVED:
    'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
}

const STATUS_LABEL: Record<AlertStatus, string> = {
  OPEN: 'Open',
  ACKNOWLEDGED: 'Acknowledged',
  RESOLVED: 'Resolved',
}

export function AlertStatusBadge({ status, className }: { status: AlertStatus; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(STATUS_STYLES[status], className)}
      data-testid="alert-status-badge"
      data-status={status}
    >
      {STATUS_LABEL[status]}
    </Badge>
  )
}

const PROFILE_STYLES: Record<MonitoringProfile, string> = {
  STANDARD: 'bg-muted text-muted-foreground border-border',
  FALL_RISK:
    'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  RESTRICTED_MOBILITY:
    'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950 dark:text-violet-300 dark:border-violet-900',
}

const PROFILE_LABEL: Record<MonitoringProfile, string> = {
  STANDARD: 'Standard',
  FALL_RISK: 'Fall risk',
  RESTRICTED_MOBILITY: 'Restricted mobility',
}

export function MonitoringProfileBadge({
  profile,
  className,
}: {
  profile: MonitoringProfile
  className?: string
}) {
  return (
    <Badge
      variant="outline"
      className={cn(PROFILE_STYLES[profile], className)}
      data-testid="monitoring-profile-badge"
      data-profile={profile}
    >
      {PROFILE_LABEL[profile]}
    </Badge>
  )
}
