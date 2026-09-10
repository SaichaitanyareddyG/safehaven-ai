import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { createInstruction } from '@/api/instructions'
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
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api-client'

const schema = z.object({
  text: z.string().trim().min(1, 'Enter the clinical instruction text'),
})

type FormValues = z.infer<typeof schema>

export function CreateInstructionDialog({ patientId }: { patientId: string }) {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const mutation = useMutation({
    mutationFn: (values: FormValues) => createInstruction(patientId, values.text),
    onSuccess: (instruction) => {
      queryClient.invalidateQueries({ queryKey: ['patient-instructions', patientId] })
      setOpen(false)
      reset()
      navigate(`/instructions/${instruction.id}`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to create instruction')
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="instruction-new-button">
          <Plus className="h-4 w-4" />
          New Instruction
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Enter a clinical instruction</DialogTitle>
          <DialogDescription>
            Write it exactly as you would for the chart. AI will analyze it in the next step — nothing is sent to
            the patient yet.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
          <div className="space-y-2">
            <Label htmlFor="text">Clinical instruction</Label>
            <Textarea
              id="text"
              rows={4}
              placeholder="e.g. Take Metoprolol 25 mg orally twice daily with food."
              {...register('text')}
            />
            {errors.text && <p className="text-sm text-destructive">{errors.text.message}</p>}
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={isSubmitting || mutation.isPending}
              data-testid="instruction-create-submit"
            >
              {mutation.isPending ? 'Creating…' : 'Create instruction'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
