import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { analyzeInstruction, generatePatientOutput, getInstruction, requestTranslations } from '@/api/instructions'
import { getPatient } from '@/api/patients'
import { AiProcessingOverlay } from '@/components/AiProcessingOverlay'
import { AppLayout } from '@/components/AppLayout'
import { InstructionStatusBadge } from '@/components/StatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ClarificationForm } from '@/features/instructions/ClarificationForm'
import { FactsPanel } from '@/features/instructions/FactsPanel'
import {
  AnalyzeButton,
  ApproveButton,
  GenerateButton,
  MedicationStatusControl,
  RejectDialog,
} from '@/features/instructions/InstructionActions'
import { PatientOutputPanel } from '@/features/instructions/PatientOutputPanel'
import { TranslationsPanel } from '@/features/instructions/TranslationsPanel'
import { VersionHistory } from '@/features/instructions/VersionHistory'
import { ANALYZE_STEPS, GENERATE_STEPS, TRANSLATE_STEPS } from '@/lib/ai-processing-steps'
import { ApiError } from '@/lib/api-client'

export function InstructionWorkflowPage() {
  const { instructionId } = useParams<{ instructionId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: instruction, isLoading, isError } = useQuery({
    queryKey: ['instruction', instructionId],
    queryFn: () => getInstruction(instructionId!),
    enabled: !!instructionId,
  })

  const { data: patient } = useQuery({
    queryKey: ['patient', instruction?.patient_id],
    queryFn: () => getPatient(instruction!.patient_id),
    enabled: !!instruction,
  })

  const version = instruction?.current_version
  const extraction = version?.extraction ?? null
  const latestOutput = version?.patient_outputs.at(-1) ?? null

  // Auto-chain the AI *processing* steps only — analyze and generate never
  // expose anything to a patient, so there's no safety reason to require a
  // click. Approval stays a deliberate, manual clinician action always (see
  // ApproveButton below) — that's the non-negotiable "clinician approves"
  // half of "AI proposes, validation decides, clinician approves", not a UX
  // choice. Translation auto-triggers only after approval, only for the
  // patient's own preferred language, and is still independently validated
  // before it can ever reach the patient — see requestTranslations.
  const analyzedRef = useRef(false)
  const generatedRef = useRef(false)
  const translatedRef = useRef(false)

  const invalidateInstruction = (updated: { patient_id: string }) => {
    queryClient.setQueryData(['instruction', instructionId], (previous: typeof instruction) =>
      previous ? { ...previous, ...updated } : previous,
    )
    queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
    queryClient.invalidateQueries({ queryKey: ['patient-instructions', updated.patient_id] })
  }

  const autoAnalyzeMutation = useMutation({
    mutationFn: () => analyzeInstruction(instructionId!),
    onSuccess: invalidateInstruction,
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? `Automatic analysis failed: ${error.message}` : 'Automatic analysis failed',
      )
    },
  })

  const autoGenerateMutation = useMutation({
    mutationFn: () => generatePatientOutput(instructionId!),
    onSuccess: invalidateInstruction,
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? `Automatic generation failed: ${error.message}` : 'Automatic generation failed',
      )
    },
  })

  const autoTranslateMutation = useMutation({
    mutationFn: (languages: Array<'TELUGU' | 'HINDI'>) => requestTranslations(instructionId!, languages),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
      toast.success('Preferred-language translation complete')
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? `Automatic translation failed: ${error.message}` : 'Automatic translation failed',
      )
    },
  })

  useEffect(() => {
    if (!instruction || analyzedRef.current || autoAnalyzeMutation.isPending) return
    if (instruction.status === 'DRAFT') {
      analyzedRef.current = true
      autoAnalyzeMutation.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instruction?.status])

  useEffect(() => {
    if (!instruction || generatedRef.current || autoGenerateMutation.isPending) return
    if (instruction.status === 'PROCESSING' && extraction?.completeness_status === 'PASSED' && !latestOutput) {
      generatedRef.current = true
      autoGenerateMutation.mutate()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instruction?.status, extraction?.completeness_status, latestOutput])

  useEffect(() => {
    if (!instruction || !patient || !latestOutput || translatedRef.current || autoTranslateMutation.isPending) return
    if (instruction.status !== 'APPROVED') return
    if (patient.preferred_language === 'ENGLISH') return
    const alreadyTranslated = latestOutput.translations.some((t) => t.language === patient.preferred_language)
    if (alreadyTranslated) return
    translatedRef.current = true
    autoTranslateMutation.mutate([patient.preferred_language as 'TELUGU' | 'HINDI'])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instruction?.status, patient?.preferred_language, latestOutput])

  if (isLoading) {
    return (
      <AppLayout>
        <Skeleton className="h-64 w-full" />
      </AppLayout>
    )
  }

  if (isError || !instruction) {
    return (
      <AppLayout>
        <p className="text-sm text-destructive">Failed to load instruction.</p>
      </AppLayout>
    )
  }

  const canReject = instruction.status === 'NEEDS_REVIEW' || instruction.status === 'READY_FOR_APPROVAL'

  return (
    <AppLayout>
      <AiProcessingOverlay title="AI Analysis" steps={ANALYZE_STEPS} active={autoAnalyzeMutation.isPending} />
      <AiProcessingOverlay
        title="Generating Patient-Friendly Version"
        steps={GENERATE_STEPS}
        active={autoGenerateMutation.isPending}
      />
      <AiProcessingOverlay title="Translating for Patient" steps={TRANSLATE_STEPS} active={autoTranslateMutation.isPending} />

      <Button variant="ghost" size="sm" className="mb-4 -ml-2" onClick={() => navigate(`/patients/${instruction.patient_id}`)}>
        <ArrowLeft className="h-4 w-4" />
        Back to patient
      </Button>

      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Clinical Instruction</h1>
          <p className="text-sm text-muted-foreground">
            Created {version && format(new Date(instruction.created_at), 'PPp')}
          </p>
        </div>
        <InstructionStatusBadge status={instruction.status} />
      </div>

      {instruction.review_reason && (
        <Alert className="mb-6 border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950">
          <AlertTitle className="text-amber-800 dark:text-amber-300">Needs clinician attention</AlertTitle>
          <AlertDescription className="text-amber-700 dark:text-amber-400">
            {instruction.review_reason}
          </AlertDescription>
        </Alert>
      )}

      {instruction.status === 'APPROVED' && (
        <Alert className="mb-6 border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950">
          <AlertTitle className="text-emerald-800 dark:text-emerald-300">Approved</AlertTitle>
          <AlertDescription className="text-emerald-700 dark:text-emerald-400">
            Approved {instruction.approved_at && format(new Date(instruction.approved_at), 'PPp')}. The patient
            can now view this instruction.
          </AlertDescription>
        </Alert>
      )}

      {instruction.clinical_status && (
        <div className="mb-6">
          <MedicationStatusControl instructionId={instruction.id} status={instruction.clinical_status} />
        </div>
      )}

      <div className="space-y-6">
        <Card>
          <CardHeader className="pb-2">
            <p className="text-sm font-medium">Original clinical instruction</p>
          </CardHeader>
          <CardContent>
            <p className="rounded-lg border bg-muted/30 p-4 text-sm leading-relaxed">{version?.raw_text}</p>
          </CardContent>
        </Card>

        {instruction.status === 'DRAFT' && (
          <Card>
            <CardContent className="flex items-center justify-between py-6">
              <p className="text-sm text-muted-foreground">
                {autoAnalyzeMutation.isPending ? 'Analyzing automatically…' : 'Not yet analyzed by AI.'}
              </p>
              {!autoAnalyzeMutation.isPending && <AnalyzeButton instructionId={instruction.id} />}
            </CardContent>
          </Card>
        )}

        {extraction && (
          <Card>
            <CardHeader className="pb-2">
              <p className="text-sm font-medium">AI-extracted facts</p>
            </CardHeader>
            <CardContent className="space-y-4">
              <FactsPanel extraction={extraction} />
              {instruction.status === 'PROCESSING' &&
                extraction.completeness_status === 'PASSED' &&
                !latestOutput &&
                (autoGenerateMutation.isPending ? (
                  <p className="text-sm text-muted-foreground">Generating automatically…</p>
                ) : (
                  <GenerateButton instructionId={instruction.id} />
                ))}
            </CardContent>
          </Card>
        )}

        {latestOutput && (
          <Card>
            <CardHeader className="pb-2">
              <p className="text-sm font-medium">Patient-friendly version</p>
            </CardHeader>
            <CardContent>
              <PatientOutputPanel output={latestOutput} />
            </CardContent>
          </Card>
        )}

        {instruction.status === 'NEEDS_REVIEW' && (
          <Card>
            <CardHeader className="pb-2">
              <p className="text-sm font-medium">Clinician clarification</p>
            </CardHeader>
            <CardContent>
              <ClarificationForm instructionId={instruction.id} originalText={version?.raw_text ?? ''} />
            </CardContent>
          </Card>
        )}

        {(instruction.status === 'READY_FOR_APPROVAL' || canReject) && (
          <div className="flex items-center gap-3">
            {instruction.status === 'READY_FOR_APPROVAL' && <ApproveButton instructionId={instruction.id} />}
            {canReject && <RejectDialog instructionId={instruction.id} />}
          </div>
        )}

        {instruction.status === 'APPROVED' && latestOutput && (
          <Card>
            <CardHeader className="pb-2">
              <p className="text-sm font-medium">Telugu / Hindi translations</p>
            </CardHeader>
            <CardContent>
              <TranslationsPanel
                instructionId={instruction.id}
                translations={latestOutput.translations}
                disabled={autoTranslateMutation.isPending}
              />
            </CardContent>
          </Card>
        )}

        <VersionHistory versions={instruction.versions} />
      </div>
    </AppLayout>
  )
}
