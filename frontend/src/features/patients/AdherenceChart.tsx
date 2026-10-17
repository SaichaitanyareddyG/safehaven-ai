import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'

import { getAdherence } from '@/api/patient-app'

/** Last 14 days of what the patient reported in the app: taken, skipped,
 *  no answer, per day. Patient-reported — doses nurses gave in hospital are
 *  in Medication check, not here. */
export function AdherenceChart({ patientId }: { patientId: string }) {
  const { data } = useQuery({ queryKey: ['patient-adherence', patientId], queryFn: () => getAdherence(patientId, 14) })
  if (!data || data.total_due === 0) return null

  const noAnswer = data.total_due - data.total_taken - data.total_skipped
  const percent = Math.round((data.total_taken / data.total_due) * 100)

  return (
    <div className="space-y-2 rounded-lg border p-3" data-testid="adherence-chart">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">Doses reported in the app · last 14 days</p>
        <p className="text-sm">
          <span className="font-semibold">{percent}% taken</span>
          <span className="text-muted-foreground">
            {' '}
            · {data.total_taken} of {data.total_due} · {data.total_skipped} skipped · {noAnswer} no answer
          </span>
        </p>
      </div>
      <div className="flex h-24 items-end gap-1" role="img" aria-label={`${percent}% of doses reported taken in the last 14 days`}>
        {data.days.map((day) => {
          const none = day.due - day.taken - day.skipped
          return (
            <div key={day.date} className="flex h-full min-w-0 flex-1 flex-col justify-end" title={tooltip(day, none)}>
              {day.due === 0 ? (
                <div className="h-1 rounded-full bg-[#E1E8EC]" />
              ) : (
                <div className="flex h-full flex-col-reverse overflow-hidden rounded-sm">
                  <div className="bg-primary" style={{ height: `${(day.taken / day.due) * 100}%` }} />
                  <div className="bg-amber-400" style={{ height: `${(day.skipped / day.due) * 100}%` }} />
                  <div className="bg-[#C9D6DB]" style={{ height: `${(none / day.due) * 100}%` }} />
                </div>
              )}
            </div>
          )
        })}
      </div>
      <div className="flex justify-between text-[11px] text-muted-foreground">
        <span>{format(parseISO(data.days[0].date), 'MMM d')}</span>
        <span>Today</span>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <Legend className="bg-primary" label="Taken" />
        <Legend className="bg-amber-400" label="Skipped" />
        <Legend className="bg-[#C9D6DB]" label="No answer" />
        <span>Patient-reported. Doses given in hospital are in Medication check.</span>
      </div>
    </div>
  )
}

function tooltip(day: { date: string; due: number; taken: number; skipped: number }, none: number) {
  const when = format(parseISO(day.date), 'MMM d')
  return day.due === 0 ? `${when}: no doses due` : `${when}: ${day.taken} taken, ${day.skipped} skipped, ${none} no answer`
}

function Legend({ className, label }: { className: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-sm ${className}`} aria-hidden="true" />
      {label}
    </span>
  )
}
