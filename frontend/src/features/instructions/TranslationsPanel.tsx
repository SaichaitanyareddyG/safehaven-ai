import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Languages } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { requestTranslations } from '@/api/instructions'
import { ValidationStatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError } from '@/lib/api-client'
import { ALL_LANGUAGES, LANGUAGE_LABEL, LANGUAGE_NATIVE_LABEL } from '@/lib/language-labels'
import { fieldLabel, formatFactValue } from '@/lib/instruction-field-labels'
import type { PatientOutputTranslationRead } from '@/types/instructions'
import type { Language } from '@/types/patients'

// Every supported language except the source language itself.
const TRANSLATABLE_LANGUAGES: Language[] = ALL_LANGUAGES.filter((language) => language !== 'ENGLISH')

export function TranslationsPanel({
  instructionId,
  translations,
  disabled = false,
}: {
  instructionId: string
  translations: PatientOutputTranslationRead[]
  /** True while the workflow page's own auto-translate (preferred language) is
   * in flight — prevents a manual click racing the same language request
   * (translations are unique per (output, language), so a concurrent request
   * for the same language would fail with a raw integrity error rather than
   * the graceful lock-based retry analyze/generate get). */
  disabled?: boolean
}) {
  const queryClient = useQueryClient()
  const byLanguage = new Map(translations.map((t) => [t.language, t]))
  const missing = TRANSLATABLE_LANGUAGES.filter((lang) => !byLanguage.has(lang))
  // One language at a time: each translation is its own checked AI run, so a
  // single "translate to everything" click was slow and costly.
  const [choice, setChoice] = useState<Language | ''>('')

  const mutation = useMutation({
    mutationFn: (languages: Language[]) => requestTranslations(instructionId, languages),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
      const summary = Object.entries(result)
        .map(([lang, r]) => `${LANGUAGE_LABEL[lang as Language] ?? lang}: ${r.status === 'PASSED' ? 'ready' : 'blocked'}`)
        .join(', ')
      toast.success(`Translation complete — ${summary}`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to request translations')
    },
  })

  return (
    <div className="space-y-4">
      {missing.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Select value={choice} onValueChange={(value) => setChoice(value as Language)}>
            <SelectTrigger className="w-56" aria-label="Language to translate into" data-testid="translate-language">
              <SelectValue placeholder="Choose a language" />
            </SelectTrigger>
            <SelectContent>
              {missing.map((language) => (
                <SelectItem key={language} value={language}>
                  {LANGUAGE_LABEL[language]} · {LANGUAGE_NATIVE_LABEL[language]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            onClick={() => choice && mutation.mutate([choice])}
            disabled={!choice || mutation.isPending || disabled}
            data-testid="translate-button"
          >
            <Languages className="h-4 w-4" />
            {mutation.isPending || disabled ? 'Translating…' : 'Translate'}
          </Button>
        </div>
      )}

      {translations.length > 0 && (
        <div className="space-y-3">
          {translations.map((translation) => (
            <div
              key={translation.id}
              className="rounded-lg border p-4"
              data-testid="translation-row"
              data-language={translation.language}
              data-status={translation.validation_status}
            >
              <div className="mb-2 flex items-center justify-between">
                <p className="text-sm font-medium">
                  {LANGUAGE_LABEL[translation.language]} · {LANGUAGE_NATIVE_LABEL[translation.language]}
                </p>
                <ValidationStatusBadge status={translation.validation_status} />
              </div>
              {translation.validation_status === 'PASSED' ? (
                <p className="text-sm leading-relaxed" data-testid="translated-text">
                  {translation.translated_text}
                </p>
              ) : (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950">
                  <p className="text-sm text-red-800 dark:text-red-300">
                    Blocked — this translation will not be shown to the patient.
                  </p>
                  {translation.validation_diff.length > 0 && (
                    <ul className="mt-1 space-y-0.5 text-xs text-red-700 dark:text-red-400">
                      {translation.validation_diff.map((diff, i) => (
                        <li key={i}>
                          {fieldLabel(diff.field)}: {formatFactValue(diff.source)} → {formatFactValue(diff.generated)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
