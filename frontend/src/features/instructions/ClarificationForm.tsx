import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { clarifyInstruction } from '@/api/instructions'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api-client'

const schema = z.object({
  text: z.string().trim().min(1, 'Enter the clarified instruction text'),
})

type FormValues = z.infer<typeof schema>

export function ClarificationForm({ instructionId, originalText }: { instructionId: string; originalText: string }) {
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: { text: originalText } })

  const mutation = useMutation({
    mutationFn: (values: FormValues) => clarifyInstruction(instructionId, values.text),
    onSuccess: (updated) => {
      queryClient.setQueryData(['instruction', instructionId], updated)
      // See InstructionActions.tsx — the patient's instruction list is a
      // separate cached query and needs its own invalidation.
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', updated.patient_id] })
      toast.success('Clarification submitted — re-analyzed by AI')
      reset({ text: updated.current_version?.raw_text ?? '' })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to submit clarification')
    },
  })

  return (
    <form className="space-y-3" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
      <div className="space-y-2">
        <Label htmlFor="clarification">Revise the instruction to add the missing information</Label>
        <Textarea id="clarification" rows={4} {...register('text')} data-testid="clarification-textarea" />
        {errors.text && <p className="text-sm text-destructive">{errors.text.message}</p>}
      </div>
      <p className="text-xs text-muted-foreground">
        This creates a new, immutable version and re-runs AI analysis automatically.
      </p>
      <Button
        type="submit"
        disabled={isSubmitting || mutation.isPending}
        data-testid="clarification-submit"
      >
        {mutation.isPending ? 'Submitting…' : 'Submit clarification'}
      </Button>
    </form>
  )
}
