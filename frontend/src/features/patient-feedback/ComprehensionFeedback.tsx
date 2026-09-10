import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, HelpCircle, MessageCircleQuestion } from 'lucide-react'
import { useState } from 'react'

import { sendComprehensionFeedback } from '@/api/patient-feedback'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ComprehensionResponse } from '@/types/patient-feedback'

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

  const mutation = useMutation({
    mutationFn: (response: ComprehensionResponse) => sendComprehensionFeedback(token, instructionId, response),
    onSuccess: (_result, response) => {
      setSelected(response)
      if (response === 'HAS_QUESTION') {
        document.getElementById('patient-chat')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    },
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
      {selected && (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="comprehension-feedback-confirmation">
          {CONFIRMATION_TEXT[selected]}
        </p>
      )}
    </div>
  )
}
