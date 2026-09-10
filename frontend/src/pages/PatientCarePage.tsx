import { useQuery } from '@tanstack/react-query'
import { HeartPulse } from 'lucide-react'
import { type ReactNode, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { getCarePlan } from '@/api/patient-access'
import { ListenButton } from '@/components/ListenButton'
import { Button } from '@/components/ui/button'
import { PatientChatPanel } from '@/features/patient-chat/PatientChatPanel'
import { ComprehensionFeedback } from '@/features/patient-feedback/ComprehensionFeedback'
import { instructionIcon, instructionTypeLabel } from '@/lib/instruction-icons'
import { ALL_LANGUAGES, LANGUAGE_NATIVE_LABEL } from '@/lib/language-labels'
import { cn } from '@/lib/utils'
import type { Language } from '@/types/patients'
import type { PatientCareInstructionView, WhyExplanation } from '@/types/patient-access'

export function PatientCarePage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['care-plan', token],
    queryFn: () => getCarePlan(token!),
    enabled: !!token,
    retry: false,
  })

  const [selectedLanguage, setSelectedLanguage] = useState<Language | null>(null)
  const activeLanguage = selectedLanguage ?? data?.preferred_language ?? 'ENGLISH'

  if (!token) {
    return <CareLinkProblem message="This link is missing information. Please ask your care team for a new one." />
  }

  if (isLoading) {
    return (
      <CareShell>
        <p className="text-center text-lg text-muted-foreground">Loading your care plan…</p>
      </CareShell>
    )
  }

  if (isError || !data) {
    return <CareLinkProblem message="This link is no longer valid. Please ask your care team for a new one." />
  }

  return (
    <CareShell>
      <p className="text-xl text-muted-foreground">Hello, {data.patient_first_name}</p>
      <h1 className="mt-1 text-3xl font-bold tracking-tight sm:text-4xl">Today's Care Plan</h1>

      <div className="mt-6 flex justify-center gap-2">
        {ALL_LANGUAGES.map((language) => (
          <button
            key={language}
            onClick={() => setSelectedLanguage(language)}
            className={cn(
              'rounded-full border-2 px-5 py-2.5 text-lg font-medium transition-colors',
              activeLanguage === language
                ? 'border-primary bg-primary text-primary-foreground'
                : 'border-border bg-background text-foreground hover:bg-muted',
            )}
            data-testid={`care-language-button-${language.toLowerCase()}`}
          >
            {LANGUAGE_NATIVE_LABEL[language]}
          </button>
        ))}
      </div>

      <div className="mt-8 space-y-5 text-left">
        {data.instructions.length === 0 && (
          <p className="text-center text-lg text-muted-foreground">
            Your care team hasn't shared any instructions here yet.
          </p>
        )}
        {data.instructions.map((instruction, index) =>
          instruction.instruction_type === 'MEDICATION' ? (
            <CurrentMedicationCard key={index} instruction={instruction} language={activeLanguage} token={token} />
          ) : (
            <CareInstructionCard key={index} instruction={instruction} language={activeLanguage} token={token} />
          ),
        )}
      </div>

      {data.past_medications.length > 0 && (
        <div className="mt-8 text-left">
          <p className="mb-3 text-center text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Past Medications
          </p>
          <div className="space-y-2">
            {data.past_medications.map((instruction, index) => (
              <PastMedicationRow key={index} instruction={instruction} language={activeLanguage} />
            ))}
          </div>
        </div>
      )}

      <div id="patient-chat" className="mt-5 scroll-mt-6">
        <PatientChatPanel token={token} />
      </div>
    </CareShell>
  )
}

function CurrentMedicationCard({
  instruction,
  language,
  token,
}: {
  instruction: PatientCareInstructionView
  language: Language
  token: string
}) {
  const [isOpen, setIsOpen] = useState(false)
  const text = instruction.text_by_language[language] ?? instruction.text_by_language.ENGLISH

  if (isOpen) {
    return <CareInstructionCard instruction={instruction} language={language} token={token} />
  }

  return (
    <div className="rounded-2xl border-2 bg-background p-6 shadow-sm sm:p-8" data-testid="current-medication-summary">
      <p className="text-2xl font-semibold">
        <span aria-hidden="true">{instructionIcon('MEDICATION')}</span> Medication
      </p>
      <p className="mt-3 line-clamp-2 text-lg text-muted-foreground">{text}</p>
      <Button className="mt-4" onClick={() => setIsOpen(true)} data-testid="understand-medicine-button">
        Understand this medicine
      </Button>
    </div>
  )
}

function PastMedicationRow({ instruction, language }: { instruction: PatientCareInstructionView; language: Language }) {
  const text = instruction.text_by_language[language] ?? instruction.text_by_language.ENGLISH
  return (
    <div
      className="rounded-xl border bg-muted/20 px-5 py-3 text-left text-muted-foreground"
      data-testid="past-medication-row"
    >
      <p className="text-base">{text}</p>
    </div>
  )
}

function CareInstructionCard({
  instruction,
  language,
  token,
}: {
  instruction: PatientCareInstructionView
  language: Language
  token: string
}) {
  const text = instruction.text_by_language[language] ?? instruction.text_by_language.ENGLISH
  const isFallback = !instruction.text_by_language[language] && language !== 'ENGLISH'

  return (
    <div className="rounded-2xl border-2 bg-background p-6 shadow-sm sm:p-8" data-testid="care-instruction-card">
      <p className="text-2xl font-semibold">
        <span aria-hidden="true">{instructionIcon(instruction.instruction_type)}</span>{' '}
        {instructionTypeLabel(instruction.instruction_type)}
      </p>
      <p className="mt-4 text-2xl leading-relaxed sm:text-3xl" data-testid="care-instruction-text">
        {text}
      </p>
      {isFallback && (
        <p className="mt-3 text-base text-muted-foreground">
          {LANGUAGE_NATIVE_LABEL[language]} isn't available for this yet — showing English.
        </p>
      )}
      {text && (
        <div className="mt-5">
          <ListenButton text={text} language={isFallback ? 'ENGLISH' : language} token={token} />
        </div>
      )}
      {instruction.why && <WhyExplanationBlock why={instruction.why} />}
      <ComprehensionFeedback token={token} instructionId={instruction.id} />
    </div>
  )
}

function WhyExplanationBlock({ why }: { why: WhyExplanation }) {
  const isDocumented = why.tier === 'DOCUMENTED'
  return (
    <div
      className={cn(
        'mt-5 rounded-xl border-2 p-4 text-left',
        isDocumented ? 'border-primary/30 bg-primary/5' : 'border-border bg-muted/40',
      )}
      data-testid="why-explanation"
      data-tier={why.tier}
    >
      <p className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {isDocumented ? "Why you're taking/doing this" : 'General information about this medicine'}
      </p>
      <p className="mt-1 text-lg leading-relaxed">{why.text}</p>
      {why.disclaimer && (
        <p className="mt-2 text-sm text-muted-foreground" data-testid="why-disclaimer">
          {why.disclaimer}
        </p>
      )}
    </div>
  )
}

function CareShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-muted/20">
      <header className="border-b bg-background py-4">
        <div className="mx-auto flex max-w-2xl items-center justify-center gap-2 px-4">
          <HeartPulse className="h-6 w-6 text-primary" />
          <span className="text-lg font-semibold tracking-tight">SafeHaven AI</span>
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-10 text-center">{children}</main>
    </div>
  )
}

function CareLinkProblem({ message }: { message: string }) {
  return (
    <CareShell>
      <p className="text-xl text-muted-foreground">{message}</p>
    </CareShell>
  )
}
