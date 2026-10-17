import { AlertTriangle, BellRing, Clock } from 'lucide-react'

import { formatDate } from '@/lib/format'
import type { DoseSchedule } from '@/types/dose-schedule'

/** What the patient app will remind at, shown before approval: approving the
 *  instruction approves these times. Built by fixed rules from the facts
 *  above — to change it, change the instruction text. */
export function DoseSchedulePanel({ schedule }: { schedule: DoseSchedule }) {
  if (schedule.kind === 'NEEDS_REVIEW') {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950" data-testid="dose-schedule" data-kind={schedule.kind}>
        <p className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4" />
          No dose times for this medicine
        </p>
        <p className="mt-1 text-sm text-amber-900 dark:text-amber-200">{schedule.problem}</p>
        <p className="mt-1 text-xs text-amber-900/80 dark:text-amber-200/80">
          The patient still sees the instruction. For dose times, write how often in plain terms (e.g. "twice daily",
          "every 8 hours", "at bedtime") and the course length (e.g. "for 7 days").
        </p>
      </div>
    )
  }

  if (schedule.kind === 'AS_NEEDED') {
    return (
      <div className="rounded-lg border p-3" data-testid="dose-schedule" data-kind={schedule.kind}>
        <p className="flex items-center gap-2 text-sm font-medium">
          <BellRing className="h-4 w-4 text-muted-foreground" />
          Patient dose times: none — as needed
        </p>
        <p className="mt-1 text-xs text-muted-foreground">An as-needed medicine has no set times, so the app never lists it as a dose due.</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border p-3" data-testid="dose-schedule" data-kind={schedule.kind}>
      <p className="flex items-center gap-2 text-sm font-medium">
        <BellRing className="h-4 w-4 text-primary" />
        Patient dose times
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {schedule.times_display.map((t) => (
          <span key={t} className="flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-sm font-medium text-primary">
            <Clock className="h-3.5 w-3.5" />
            {t}
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm text-muted-foreground">
        {schedule.dose && <>{schedule.dose} each time · </>}
        {schedule.times.length} {schedule.times.length === 1 ? 'dose' : 'doses'} a day
        {schedule.with_food ? ' · with food' : ''} ·{' '}
        {schedule.duration_days
          ? schedule.start_date && schedule.end_date
            ? `${formatDate(schedule.start_date)} – ${formatDate(schedule.end_date)} (${schedule.duration_days} days)`
            : `for ${schedule.duration_days} days from approval`
          : 'ongoing, until stopped'}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        Hospital standard dose times, shown in the patient app as today's doses. In hospital, nurses give the doses.
      </p>
    </div>
  )
}
