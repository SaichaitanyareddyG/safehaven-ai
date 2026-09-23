import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, HelpCircle, MessageCircleQuestion } from 'lucide-react'
import { useState } from 'react'

import { sendComprehensionFeedback, sendTeachBack } from '@/api/patient-feedback'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { ComprehensionResponse, TeachBackResult } from '@/types/patient-feedback'

const FACT_LABELS: Record<string, string> = {
  medication_name: 'the name of the medicine',
  timing: 'how often you take it',
  reason: 'why you take it',
}

const OPTIONS: { value: ComprehensionResponse; label: string; icon: typeof CheckCircle2 }[] = [
  { value: 'UNDERSTOOD', label: 'Yes, I understand', icon: CheckCircle2 },
  { value: 'HAS_QUESTION', label: 'I still have a question', icon: HelpCircle },
  { value: 'ASK_CARE_TEAM', label: 'Ask my care team', icon: MessageCircleQuestion },
]

const CONFIRMATION_TEXT: Record<ComprehensionResponse, string> = {
  UNDERSTOOD: "Great — glad that's clear.",
  HAS_QUESTION: 'No problem — ask below and I’ll do my best to help.',
  ASK_CARE_TEAM: "Okay — please reach out to your care team when you're able.",
}

export function ComprehensionFeedback({ token, instructionId }: { token: string; instructionId: string }) {
  const [selected, setSelected] = useState<ComprehensionResponse | null>(null)
  const [teachBackText, setTeachBackText] = useState('')
  const [teachBackResult, setTeachBackResult] = useState<TeachBackResult | null>(null)

  const mutation = useMutation({
    mutationFn: (response: ComprehensionResponse) => sendComprehensionFeedback(token, instructionId, response),
    onSuccess: (_result, response) => {
      setSelected(response)
      setTeachBackResult(null)
      if (response === 'HAS_QUESTION') {
        document.getElementById('patient-chat')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    },
  })

  const teachBackMutation = useMutation({
    mutationFn: () => sendTeachBack(token, instructionId, teachBackText),
    onSuccess: (result) => setTeachBackResult(result),
  })

  return (
    <div className="mt-5 border-t pt-4" data-testid="comprehension-feedback">
      <p className="text-sm font-medium text-muted-foreground">Did this explanation help?</p>
      <div className="mt-2 flex flex-wrap gap-2">
        {OPTIONS.map(({ value, label, icon: Icon }) => (
          <Button
            key={value}
            type="button"
            variant={selected === value ? 'default' : 'outline'}
            size="sm"
            disabled={mutation.isPending}
            onClick={() => mutation.mutate(value)}
            className={cn(selected && selected !== value && 'opacity-50')}
            data-testid="comprehension-feedback-button"
            data-response={value}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Button>
        ))}
      </div>

      {selected && selected !== 'UNDERSTOOD' && (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="comprehension-feedback-confirmation">
          {CONFIRMATION_TEXT[selected]}
        </p>
      )}

      {selected === 'UNDERSTOOD' && !teachBackResult && (
        <div className="mt-3 space-y-2" data-testid="teach-back-prompt">
          <p className="text-sm text-muted-foreground">
            Just to double check — in your own words, what do you take and why?
          </p>
          <Textarea
            value={teachBackText}
            onChange={(e) => setTeachBackText(e.target.value)}
            placeholder="e.g. I take my Lisinopril once daily for my blood pressure."
            rows={2}
            data-testid="teach-back-input"
          />
          <Button
            type="button"
            size="sm"
            disabled={teachBackMutation.isPending || !teachBackText.trim()}
            onClick={() => teachBackMutation.mutate()}
            data-testid="teach-back-submit"
          >
            Check my answer
          </Button>
        </div>
      )}

      {teachBackResult && (
        <div className="mt-3 space-y-1" data-testid="teach-back-result">
          {teachBackResult.passed ? (
            <p className="text-sm font-medium text-green-700 dark:text-green-500">
              That's exactly right — well explained.
            </p>
          ) : (
            <>
              <p className="text-sm font-medium text-amber-700 dark:text-amber-500">
                Thanks — let's double check a couple things. Your answer didn't mention{' '}
                {teachBackResult.missing_facts.map((f) => FACT_LABELS[f] ?? f).join(', ')}.
              </p>
              <p className="text-sm text-muted-foreground">
                Take another look above, or ask below and I'll do my best to help.
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}
