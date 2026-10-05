import { AlertTriangle, BookOpen, ShieldCheck } from 'lucide-react'

import { ValidationStatusBadge } from '@/components/StatusBadge'
import { fieldLabel, formatFactValue } from '@/lib/instruction-field-labels'
import type { PatientOutputRead } from '@/types/instructions'

// AMA/CDC guidance targets roughly a 5th-6th grade reading level for patient
// materials — informational only, never blocks approval (see
// PatientOutput.reading_grade_level's backend docstring for why).
const READABILITY_TARGET_GRADE = 6

export function PatientOutputPanel({ output }: { output: PatientOutputRead }) {
  const passed = output.validation_status === 'PASSED'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">Attempt {output.attempt_number}</p>
        <ValidationStatusBadge status={output.validation_status} />
      </div>

      {output.reading_grade_level !== null && (
        <p
          // Informational only, so neutral grey — amber read as a warning on
          // text that had passed every safety check.
          className="flex items-center gap-2 text-sm text-muted-foreground"
          data-testid="reading-grade-level"
        >
          <BookOpen className="h-4 w-4" />
          Reading level: grade {output.reading_grade_level} (target: grade {READABILITY_TARGET_GRADE} or below)
        </p>
      )}

      {output.patient_text_en ? (
        <div
          className={`rounded-lg border p-4 text-sm leading-relaxed ${passed ? 'bg-background' : 'border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950'}`}
          data-testid="patient-friendly-text"
        >
          {output.patient_text_en}
        </div>
      ) : (
        <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
          AI did not return any text for this attempt.
        </p>
      )}

      {passed ? (
        <p className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
          <ShieldCheck className="h-4 w-4" />
          Every clinical fact was verified preserved — safe to show the patient once approved.
        </p>
      ) : (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
          <p className="flex items-center gap-2 text-sm font-medium text-red-800 dark:text-red-300">
            <AlertTriangle className="h-4 w-4" />
            Blocked — SafeHaven caught a difference from the original
          </p>
          <ul className="mt-2 list-inside list-disc space-y-1 text-sm text-red-700 dark:text-red-400">
            {output.validation_diff.length > 0
              ? output.validation_diff.map((diff, i) => <li key={i}>{describeDifference(diff)}</li>)
              : output.validation_messages.map((message, i) => <li key={i}>{message}</li>)}
          </ul>
        </div>
      )}
    </div>
  )
}

/** One plain sentence per difference the safety check found. */
function describeDifference(diff: PatientOutputRead['validation_diff'][number]): string {
  const label = fieldLabel(diff.field)
  switch (diff.type) {
    case 'CHANGED':
      return `${label} changed: your instruction says “${formatFactValue(diff.source)}”, the friendly version says “${formatFactValue(diff.generated)}”.`
    case 'MISSING':
      return diff.source !== null && diff.source !== undefined
        ? `${label} (“${formatFactValue(diff.source)}”) is missing from the friendly version.`
        : `${label} is missing from the friendly version.`
    case 'ADDED':
      return `The friendly version added ${label.toLowerCase()} (“${formatFactValue(diff.generated)}”) that isn't in your instruction.`
    default:
      return `The friendly version doesn't say ${label.toLowerCase()} clearly.`
  }
}
