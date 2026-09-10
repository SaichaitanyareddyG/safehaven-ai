import { useQuery } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { useNavigate } from 'react-router-dom'

import { listPatientInstructions } from '@/api/instructions'
import { InstructionStatusBadge } from '@/components/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'

export function InstructionList({ patientId }: { patientId: string }) {
  const navigate = useNavigate()

  const { data, isLoading, isError } = useQuery({
    queryKey: ['patient-instructions', patientId],
    queryFn: () => listPatientInstructions(patientId, { limit: 50 }),
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return <p className="text-sm text-destructive">Failed to load instructions.</p>
  }

  if (!data || data.results.length === 0) {
    return (
      <p className="rounded-lg border border-dashed py-8 text-center text-sm text-muted-foreground">
        No instructions yet. Create one to get started.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {data.results.map((instruction) => (
        <button
          key={instruction.id}
          onClick={() => navigate(`/instructions/${instruction.id}`)}
          className="flex w-full items-start justify-between gap-4 rounded-lg border bg-background p-4 text-left transition-colors hover:bg-muted/50"
          data-testid="instruction-row"
        >
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              {instruction.current_version?.raw_text ?? '(no text)'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Created {formatDistanceToNow(new Date(instruction.created_at), { addSuffix: true })}
              {instruction.review_reason && (
                <span className="text-amber-700 dark:text-amber-400"> · {instruction.review_reason}</span>
              )}
            </p>
          </div>
          <InstructionStatusBadge status={instruction.status} className="shrink-0" />
        </button>
      ))}
    </div>
  )
}
