import { AlertTriangle, ShieldCheck } from 'lucide-react'

import { ValidationStatusBadge } from '@/components/StatusBadge'
import { formatFactValue } from '@/lib/instruction-field-labels'
import type { PatientOutputRead } from '@/types/instructions'

export function PatientOutputPanel({ output }: { output: PatientOutputRead }) {
  const passed = output.validation_status === 'PASSED'

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Patient-friendly version (attempt {output.attempt_number})</p>
        <ValidationStatusBadge status={output.validation_status} />
      </div>

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
          {output.validation_diff.length > 0 && (
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="text-red-700 dark:text-red-400">
                    <th className="pb-1 pr-3 font-medium">Field</th>
                    <th className="pb-1 pr-3 font-medium">Type</th>
                    <th className="pb-1 pr-3 font-medium">Original</th>
                    <th className="pb-1 font-medium">Generated</th>
                  </tr>
                </thead>
                <tbody>
                  {output.validation_diff.map((diff, i) => (
                    <tr key={i} className="text-red-800 dark:text-red-300">
                      <td className="py-1 pr-3 font-medium">{diff.field}</td>
                      <td className="py-1 pr-3">{diff.type}</td>
                      <td className="py-1 pr-3">{formatFactValue(diff.source)}</td>
                      <td className="py-1">{formatFactValue(diff.generated)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <ul className="mt-2 list-inside list-disc text-sm text-red-700 dark:text-red-400">
            {output.validation_messages.map((message, i) => (
              <li key={i}>{message}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
