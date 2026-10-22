import { AlertTriangle } from 'lucide-react'

import { formatDate } from '@/lib/format'
import type { MissedDosesFlag } from '@/types/patients'

function when(flag: MissedDosesFlag) {
  const today = new Date()
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  const yesterday = new Date(today.getTime() - 86400000)
  if (flag.date === iso(today)) return 'today'
  if (flag.date === iso(yesterday)) return 'yesterday'
  return `on ${formatDate(flag.date)}`
}

/** Small badge for the patient list. */
export function MissedDosesBadge({ flag }: { flag: MissedDosesFlag }) {
  return (
    <span
      className="mt-1 inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900"
      data-testid="missed-doses-badge"
      title={`${flag.missed} doses missed ${when(flag)} (${flag.skipped} skipped)`}
    >
      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
      Missed {flag.missed} doses {when(flag)}
    </span>
  )
}

/** Banner on the patient page. */
export function MissedDosesBanner({ flag }: { flag: MissedDosesFlag }) {
  const noAnswer = flag.missed - flag.skipped
  return (
    <div
      className="mb-6 flex gap-3 rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-950"
      role="status"
      data-testid="missed-doses-banner"
    >
      <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-700" aria-hidden="true" />
      <div className="text-sm">
        <p className="font-semibold">
          Missed {flag.missed} doses {when(flag)} at home
        </p>
        <p className="mt-0.5">
          {[flag.skipped && `${flag.skipped} skipped`, noAnswer && `${noAnswer} not answered`].filter(Boolean).join(', ')} in
          the patient app. Consider a call to check in. Patient-reported, not a clinical record.
        </p>
      </div>
    </div>
  )
}
