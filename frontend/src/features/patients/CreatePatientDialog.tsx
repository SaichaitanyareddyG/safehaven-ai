import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { createPatient } from '@/api/patients'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError } from '@/lib/api-client'
import { ALL_LANGUAGES, LANGUAGE_NATIVE_LABEL } from '@/lib/language-labels'
import type { Language } from '@/types/patients'

const patientSchema = z.object({
  first_name: z.string().min(1, 'First name is required'),
  last_name: z.string().min(1, 'Last name is required'),
  date_of_birth: z
    .string()
    .min(1, 'Date of birth is required')
    .refine((value) => new Date(value) <= new Date(), 'Date of birth cannot be in the future'),
  room_number: z.string().optional(),
  // Required in the form even though the API accepts it as optional — the
  // whole point is that registration should ask, not that the server insists.
  reason_for_visit: z.string().trim().min(1, 'Why has the patient come in?'),
  preferred_language: z.enum(ALL_LANGUAGES as [Language, ...Language[]]),
})

type PatientFormValues = z.infer<typeof patientSchema>

export function CreatePatientDialog() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    register,
    handleSubmit,
    reset,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<PatientFormValues>({
    resolver: zodResolver(patientSchema),
    defaultValues: { preferred_language: 'ENGLISH' },
  })

  const mutation = useMutation({
    mutationFn: (values: PatientFormValues) =>
      createPatient({ ...values, room_number: values.room_number || null }),
    onSuccess: (patient) => {
      queryClient.invalidateQueries({ queryKey: ['patients'] })
      toast.success(`${patient.first_name} ${patient.last_name} registered as ${patient.patient_code}`)
      setOpen(false)
      reset()
      navigate(`/patients/${patient.id}`)
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to create patient')
    },
  })

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button data-testid="patient-new-button">
          <Plus className="h-4 w-4" />
          New Patient
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register a new patient</DialogTitle>
          <DialogDescription>A patient code (e.g. P1001) will be assigned automatically.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="first_name">First name</Label>
              <Input id="first_name" {...register('first_name')} />
              {errors.first_name && <p className="text-sm text-destructive">{errors.first_name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="last_name">Last name</Label>
              <Input id="last_name" {...register('last_name')} />
              {errors.last_name && <p className="text-sm text-destructive">{errors.last_name.message}</p>}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="date_of_birth">Date of birth</Label>
              <Input id="date_of_birth" type="date" {...register('date_of_birth')} />
              {errors.date_of_birth && (
                <p className="text-sm text-destructive">{errors.date_of_birth.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="room_number">Room number</Label>
              <Input id="room_number" placeholder="Optional" {...register('room_number')} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason_for_visit">Reason for visit</Label>
            <Input
              id="reason_for_visit"
              placeholder="e.g. fever and cough for three days"
              {...register('reason_for_visit')}
            />
            {errors.reason_for_visit && (
              <p className="text-sm text-destructive">{errors.reason_for_visit.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="preferred_language">Preferred language</Label>
            <Select
              value={watch('preferred_language')}
              onValueChange={(value) => setValue('preferred_language', value as PatientFormValues['preferred_language'])}
            >
              <SelectTrigger id="preferred_language" className="w-full" data-testid="preferred-language-select">
                <SelectValue />
              </SelectTrigger>
              {/* Driven off ALL_LANGUAGES so a language added to the enum can
                  never be missing from the one place a patient's language is
                  actually set. */}
              <SelectContent>
                {ALL_LANGUAGES.map((language) => (
                  <SelectItem
                    key={language}
                    value={language}
                    data-testid={`preferred-language-option-${language.toLowerCase()}`}
                  >
                    {LANGUAGE_NATIVE_LABEL[language]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              disabled={isSubmitting || mutation.isPending}
              data-testid="patient-create-submit"
            >
              {mutation.isPending ? 'Registering…' : 'Register patient'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
