import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Sparkles, WandSparkles, XCircle } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import {
  analyzeInstruction,
  approveInstruction,
  generatePatientOutput,
  rejectInstruction,
  updateClinicalStatus,
} from '@/api/instructions'
import { AiProcessingOverlay } from '@/components/AiProcessingOverlay'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ANALYZE_STEPS, GENERATE_STEPS } from '@/lib/ai-processing-steps'
import { ApiError } from '@/lib/api-client'
import type { CareInstructionDetail, CareInstructionRead, ClinicalStatus } from '@/types/instructions'

function useInstructionMutation(
  instructionId: string,
  fn: (id: string) => Promise<CareInstructionDetail | CareInstructionRead>,
  successMessage: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => fn(instructionId),
    onSuccess: (updated) => {
      queryClient.setQueryData(['instruction', instructionId], (previous: CareInstructionDetail | undefined) =>
        previous ? { ...previous, ...updated } : previous,
      )
      queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
      // The patient's instruction list is a separate cached query — without
      // this, navigating back to the patient page can show a stale status
      // badge (e.g. still "Draft" right after approving).
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', updated.patient_id] })
      toast.success(successMessage)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Action failed')
    },
  })
}

export function AnalyzeButton({ instructionId }: { instructionId: string }) {
  const mutation = useInstructionMutation(instructionId, analyzeInstruction, 'AI analysis complete')
  return (
    <>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending} data-testid="analyze-button">
        <Sparkles className="h-4 w-4" />
        {mutation.isPending ? 'Analyzing…' : 'Analyze with AI'}
      </Button>
      <AiProcessingOverlay title="AI Analysis" steps={ANALYZE_STEPS} active={mutation.isPending} />
    </>
  )
}

export function GenerateButton({ instructionId }: { instructionId: string }) {
  const mutation = useInstructionMutation(
    instructionId,
    generatePatientOutput,
    'Patient-friendly version generated',
  )
  return (
    <>
      <Button onClick={() => mutation.mutate()} disabled={mutation.isPending} data-testid="generate-button">
        <WandSparkles className="h-4 w-4" />
        {mutation.isPending ? 'Generating…' : 'Generate Patient-Friendly Version'}
      </Button>
      <AiProcessingOverlay title="Generating Patient-Friendly Version" steps={GENERATE_STEPS} active={mutation.isPending} />
    </>
  )
}

export function ApproveButton({ instructionId }: { instructionId: string }) {
  const mutation = useInstructionMutation(instructionId, approveInstruction, 'Instruction approved')
  return (
    <Button onClick={() => mutation.mutate()} disabled={mutation.isPending} data-testid="approve-button">
      <CheckCircle2 className="h-4 w-4" />
      {mutation.isPending ? 'Approving…' : 'Approve for patient'}
    </Button>
  )
}

const rejectSchema = z.object({
  reason: z.string().trim().min(1, 'Enter a reason for rejecting this instruction'),
})

type RejectFormValues = z.infer<typeof rejectSchema>

export function RejectDialog({ instructionId }: { instructionId: string }) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<RejectFormValues>({ resolver: zodResolver(rejectSchema) })

  const mutation = useMutation({
    mutationFn: (values: RejectFormValues) => rejectInstruction(instructionId, values.reason),
    onSuccess: (updated) => {
      queryClient.setQueryData(['instruction', instructionId], (previous: CareInstructionDetail | undefined) =>
        previous ? { ...previous, ...updated } : previous,
      )
      queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', updated.patient_id] })
      toast.success('Instruction rejected')
      setOpen(false)
      reset()
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to reject instruction')
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" data-testid="reject-button">
          <XCircle className="h-4 w-4" />
          Reject
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject this instruction</DialogTitle>
          <DialogDescription>This instruction will not proceed further. It stays in the record.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
          <div className="space-y-2">
            <Label htmlFor="reason">Reason</Label>
            <Textarea id="reason" rows={3} {...register('reason')} data-testid="reject-reason-textarea" />
            {errors.reason && <p className="text-sm text-destructive">{errors.reason.message}</p>}
          </div>
          <DialogFooter>
            <Button
              type="submit"
              variant="destructive"
              disabled={isSubmitting || mutation.isPending}
              data-testid="reject-submit"
            >
              {mutation.isPending ? 'Rejecting…' : 'Reject instruction'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

const CLINICAL_STATUS_LABEL: Record<ClinicalStatus, string> = {
  ACTIVE: 'Active',
  COMPLETED: 'Completed',
  STOPPED: 'Stopped',
}

// Medication-only — this control only ever appears when the backend has
// already populated clinical_status (see ClinicalStatus's docstring on the
// backend), which happens only for an approved MEDICATION instruction.
export function MedicationStatusControl({
  instructionId,
  status,
}: {
  instructionId: string
  status: ClinicalStatus
}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (newStatus: ClinicalStatus) => updateClinicalStatus(instructionId, newStatus),
    onSuccess: (updated) => {
      queryClient.setQueryData(['instruction', instructionId], (previous: CareInstructionDetail | undefined) =>
        previous ? { ...previous, ...updated } : previous,
      )
      queryClient.invalidateQueries({ queryKey: ['instruction', instructionId] })
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', updated.patient_id] })
      toast.success('Medication status updated')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to update medication status')
    },
  })

  return (
    <div className="flex items-center gap-2" data-testid="medication-status-control">
      <span className="text-sm text-muted-foreground">Medication status</span>
      <Select
        value={status}
        onValueChange={(value) => mutation.mutate(value as ClinicalStatus)}
        disabled={mutation.isPending}
      >
        <SelectTrigger className="w-36" data-testid="medication-status-select">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(CLINICAL_STATUS_LABEL) as ClinicalStatus[]).map((value) => (
            <SelectItem key={value} value={value} data-testid={`medication-status-option-${value.toLowerCase()}`}>
              {CLINICAL_STATUS_LABEL[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
