import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { CheckCircle2, MinusCircle, XCircle } from 'lucide-react'

import { listAdministrationHistory } from '@/api/medication-verification'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { AdministrationHistoryItem, NotGivenReason } from '@/types/medication-verification'

const NOT_GIVEN_LABEL: Record<NotGivenReason, string> = {
  REFUSED: 'Patient refused',
  HELD: 'Held',
  PATIENT_UNAVAILABLE: 'Patient unavailable',
  VOMITED: 'Vomited',
  OTHER: 'Not given',
}

/**
 * The medication administration record.
 *
 * Every row here was already being written — none of it could be read back.
 * Blocked attempts are shown alongside given doses on purpose: "a wrong drug
 * was caught at this bedside" is part of the patient's medication story, not
 * an internal detail.
 */
export function AdministrationHistoryPanel({ patientId }: { patientId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['administration-history', patientId],
    queryFn: () => listAdministrationHistory(patientId),
  })

  if (isLoading) return <Skeleton className="h-32 w-full" />

  if (!data || data.results.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="administration-history-empty">
        No medication has been scanned at this patient's bedside yet.
      </p>
    )
  }

  return (
    <div className="space-y-2" data-testid="administration-history">
      {data.results.map((row) => (
        <AdministrationRow key={row.id} row={row} />
      ))}
    </div>
  )
}

function AdministrationRow({ row }: { row: AdministrationHistoryItem }) {
  const wasGiven = row.administered_at !== null
  const wasNotGiven = row.not_given_reason !== null
  const wasBlocked = row.verification_result === 'BLOCKED' || row.verification_result === 'REVIEW_REQUIRED'

  const drug = row.identified_medication_name
    ? `${row.identified_medication_name}${
        row.identified_strength_value ? ` ${row.identified_strength_value}${row.identified_strength_unit ?? ''}` : ''
      }`
    : 'Unrecognised product'

  // An unresolved scan is its own state — neither given nor deliberately
  // withheld. Showing it as "not given" would imply a decision nobody made.
  const status = wasGiven
    ? { label: 'Given', icon: CheckCircle2, tone: 'text-emerald-700 dark:text-emerald-400' }
    : wasNotGiven
      ? { label: NOT_GIVEN_LABEL[row.not_given_reason!], icon: MinusCircle, tone: 'text-amber-700 dark:text-amber-400' }
      : wasBlocked
        ? { label: 'Blocked', icon: XCircle, tone: 'text-destructive' }
        : { label: 'Verified, not yet actioned', icon: MinusCircle, tone: 'text-muted-foreground' }

  const Icon = status.icon
  const at = row.administered_at ?? row.not_given_at ?? row.created_at

  return (
    <div className="flex items-start gap-3 rounded-lg border p-3" data-testid="administration-history-row">
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', status.tone)} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="text-sm font-medium">{drug}</p>
          <p className="text-xs text-muted-foreground">{format(new Date(at), 'PPp')}</p>
        </div>
        <p className={cn('text-sm', status.tone)}>{status.label}</p>
        {row.administration_reason && (
          <p className="text-sm text-muted-foreground">Indication: {row.administration_reason}</p>
        )}
        {row.not_given_note && <p className="text-sm text-muted-foreground">{row.not_given_note}</p>}
        {wasBlocked && row.mismatch_reasons.length > 0 && (
          <p className="text-sm text-muted-foreground">
            {row.mismatch_reasons.join(', ').toLowerCase().replace(/_/g, ' ')}
          </p>
        )}
        {row.co_signed_by && <p className="text-xs text-muted-foreground">Independently co-signed</p>}
        {row.identification_method === 'IMAGE' && (
          <p className="text-xs text-muted-foreground">Identified from a label photo, not a barcode</p>
        )}
      </div>
    </div>
  )
}
