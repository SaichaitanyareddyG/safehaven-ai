import { AlertTriangle, Check } from 'lucide-react'

import { CompletenessBadge } from '@/components/StatusBadge'
import { cn } from '@/lib/utils'
import { FIELD_LABELS_BY_TYPE, INSTRUCTION_TYPE_LABEL, formatFactValue } from '@/lib/instruction-field-labels'
import type { StructuredExtractionRead } from '@/types/instructions'

export function FactsPanel({ extraction }: { extraction: StructuredExtractionRead }) {
  if (extraction.completeness_status === 'FAILED' || !extraction.instruction_type) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950">
        <p className="flex items-center gap-2 text-sm font-medium text-red-800 dark:text-red-300">
          <AlertTriangle className="h-4 w-4" />
          AI could not analyze this instruction
        </p>
        {extraction.validation_messages.map((message, i) => (
          <p key={i} className="mt-1 text-sm text-red-700 dark:text-red-400">
            {message}
          </p>
        ))}
      </div>
    )
  }

  const fields = FIELD_LABELS_BY_TYPE[extraction.instruction_type]
  const facts = extraction.normalized_facts

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{INSTRUCTION_TYPE_LABEL[extraction.instruction_type]}</p>
        <CompletenessBadge status={extraction.completeness_status} />
      </div>

      <dl className="divide-y rounded-lg border">
        {fields.map(([key, label]) => {
          const value = facts[key]
          const isMissing = value === null || value === undefined || (Array.isArray(value) && value.length === 0)
          const requiresClarification = extraction.clarification_required_fields.includes(key)
          const isAmbiguous = extraction.ambiguous_fields.includes(key)

          return (
            <div
              key={key}
              className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm"
              data-testid="fact-row"
              data-field={key}
            >
              <dt className="text-muted-foreground">{label}</dt>
              <dd
                className={cn(
                  'flex items-center gap-1.5 text-right font-medium',
                  isMissing && !requiresClarification && 'text-muted-foreground font-normal',
                  requiresClarification && 'text-amber-700 dark:text-amber-400',
                  isAmbiguous && 'text-amber-700 dark:text-amber-400',
                )}
                data-testid="fact-value"
              >
                {!isMissing && !isAmbiguous && <Check className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />}
                {(requiresClarification || isAmbiguous) && <AlertTriangle className="h-3.5 w-3.5" />}
                {formatFactValue(value)}
              </dd>
            </div>
          )
        })}
      </dl>

      {extraction.clarification_required_fields.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950">
          <p className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-4 w-4" />
            Clarification needed
          </p>
          <ul className="mt-1 list-inside list-disc text-sm text-amber-700 dark:text-amber-400">
            {extraction.validation_messages.map((message, i) => (
              <li key={i}>{message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
