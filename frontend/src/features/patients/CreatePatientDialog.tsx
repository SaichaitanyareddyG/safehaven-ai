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
import { ApiError } from '@/lib/api-client'

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
  email: z.union([z.literal(''), z.string().trim().email('Enter a valid email address')]).optional(),
  phone: z.string().optional(),
  app_consent: z.boolean().optional(),
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
    watch,
    formState: { errors, isSubmitting },
  } = useForm<PatientFormValues>({
    resolver: zodResolver(patientSchema),
    defaultValues: { app_consent: false },
  })
  const email = watch('email')?.trim() ?? ''
  const consent = watch('app_consent') ?? false

  const mutation = useMutation({
    mutationFn: (values: PatientFormValues) =>
      createPatient({
        ...values,
        // English only.
        preferred_language: 'ENGLISH',
        room_number: values.room_number || null,
        email: values.email?.trim() || null,
        phone: values.phone?.trim() || null,
        app_consent: !!values.email?.trim() && !!values.app_consent,
      }),
    onSuccess: (patient) => {
      queryClient.invalidateQueries({ queryKey: ['patients'] })
      toast.success(`${patient.first_name} ${patient.last_name} registered as ${patient.patient_code}`)
      const invite = patient.app_invite
      if (invite?.emailed) toast.success(`Patient app invite emailed to ${patient.email}`)
      else if (invite) {
        toast.warning(`Patient app invite not sent: ${invite.problem ?? 'unknown problem'}`, {
          description: 'You can send it again from the Patient app section.',
        })
      }
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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Register a new patient</DialogTitle>
          <DialogDescription>A patient code (e.g. P1001) will be assigned automatically.</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit((values) => mutation.mutate(values))} noValidate>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="first_name">First name</Label>
              <Input id="first_name" aria-invalid={!!errors.first_name} {...register('first_name')} />
              {errors.first_name && <p className="text-sm text-destructive">{errors.first_name.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="last_name">Last name</Label>
              <Input id="last_name" aria-invalid={!!errors.last_name} {...register('last_name')} />
              {errors.last_name && <p className="text-sm text-destructive">{errors.last_name.message}</p>}
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="date_of_birth">Date of birth</Label>
              {/* iOS gives a date field its own size and look; keep it the same box as the others. */}
              <Input
                id="date_of_birth"
                aria-invalid={!!errors.date_of_birth}
                type="date"
                className="block min-w-0 appearance-none text-left [&::-webkit-date-and-time-value]:text-left"
                {...register('date_of_birth')}
              />
              {errors.date_of_birth && (
                <p className="text-sm text-destructive">{errors.date_of_birth.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="room_number">Room number</Label>
              <Input id="room_number" aria-invalid={!!errors.room_number} placeholder="Optional" {...register('room_number')} />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="reason_for_visit">Reason for visit</Label>
            <Input
              id="reason_for_visit"
              aria-invalid={!!errors.reason_for_visit}
              placeholder="e.g. fever and cough for three days"
              {...register('reason_for_visit')}
            />
            {errors.reason_for_visit && (
              <p className="text-sm text-destructive">{errors.reason_for_visit.message}</p>
            )}
          </div>
          <fieldset className="space-y-4 rounded-lg border p-4">
            <legend className="px-1 text-sm font-medium">Patient app</legend>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="email">Patient's email</Label>
                <Input
                  id="email"
                  type="email"
                  inputMode="email"
                  autoComplete="off"
                  placeholder="Optional"
                  aria-invalid={!!errors.email}
                  {...register('email')}
                />
                {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="phone">Mobile</Label>
                <Input id="phone" type="tel" inputMode="tel" placeholder="Optional" {...register('phone')} />
              </div>
            </div>
            <label className="flex items-start gap-3 text-sm leading-snug">
              <input
                type="checkbox"
                className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                disabled={!email}
                data-testid="patient-app-consent"
                {...register('app_consent')}
              />
              <span>The patient agreed to use the SafeHaven app and to receive emails about it.</span>
            </label>
            <p className="text-xs text-muted-foreground">
              {email && consent
                ? 'On saving, the patient gets an email with a link to sign in. Their medicines, visits and instructions appear as you approve them.'
                : 'No email? Leave it blank — the printed care link still works, and you can invite them later.'}
            </p>
          </fieldset>
          <DialogFooter>
            <Button
              type="submit"
              disabled={isSubmitting || mutation.isPending}
              data-testid="patient-create-submit"
            >
              {mutation.isPending ? 'Registering…' : email && consent ? 'Register and send invite' : 'Register patient'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
