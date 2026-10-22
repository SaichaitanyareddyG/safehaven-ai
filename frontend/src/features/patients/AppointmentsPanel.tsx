import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { createAppointment, listAppointments, updateAppointment } from '@/api/appointments'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ApiError } from '@/lib/api-client'
import { formatDateTime } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useNow } from '@/lib/use-now'

/** Book, see and cancel the patient's appointments. Shown in the patient app
 *  with reminders the evening before and 2 hours before. */
export function AppointmentsPanel({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['appointments', patientId],
    queryFn: () => listAppointments(patientId),
  })
  const [adding, setAdding] = useState(false)
  const [title, setTitle] = useState('')
  const [when, setWhen] = useState('')
  const [location, setLocation] = useState('')
  const [notes, setNotes] = useState('')

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ['appointments', patientId] })
    queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
  }

  const create = useMutation({
    // datetime-local is the staff member's local time; send it with its zone.
    mutationFn: () =>
      createAppointment(patientId, {
        title: title.trim(),
        starts_at: new Date(when).toISOString(),
        location: location.trim() || null,
        notes: notes.trim() || null,
      }),
    onSuccess: () => {
      refresh()
      setAdding(false)
      setTitle('')
      setWhen('')
      setLocation('')
      setNotes('')
      toast.success('Appointment booked — the patient sees it in the app')
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not book the appointment'),
  })

  const cancel = useMutation({
    mutationFn: (id: string) => updateAppointment(id, { status: 'CANCELLED' }),
    onSuccess: () => {
      refresh()
      toast.success('Appointment cancelled')
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not cancel'),
  })

  const now = useNow()
  const appointments = data?.results ?? []
  const upcoming = appointments.filter((a) => a.status === 'SCHEDULED' && new Date(a.starts_at).getTime() >= now)
  const other = appointments.filter((a) => !upcoming.includes(a)).reverse()
  const canSave = title.trim() && when && new Date(when).getTime() > now && !create.isPending

  return (
    <div className="space-y-3" data-testid="appointments-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Appointments</p>
        {!adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="appointment-add">
            <CalendarPlus className="h-4 w-4" />
            Book appointment
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Shown in the patient app, with a reminder the evening before and 2 hours before (no details on the lock screen).
      </p>

      {adding && (
        <div className="space-y-3 rounded-lg border border-dashed p-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="appt-title" className="text-xs">
                What it is (the patient sees this)
              </Label>
              <Input id="appt-title" placeholder="e.g. Cardiology check-up" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div className="space-y-1">
              <Label htmlFor="appt-when" className="text-xs">
                Date and time
              </Label>
              <Input id="appt-when" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="appt-where" className="text-xs">
                Where
              </Label>
              <Input id="appt-where" placeholder="e.g. Clinic B, 2nd floor" value={location} onChange={(e) => setLocation(e.target.value)} />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="appt-notes" className="text-xs">
                Note for the patient (optional)
              </Label>
              <Textarea
                id="appt-notes"
                rows={2}
                placeholder="e.g. Bring your medicines. Nothing to eat after midnight."
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button size="sm" disabled={!canSave} onClick={() => create.mutate()} data-testid="appointment-save">
              {create.isPending ? 'Booking…' : 'Book'}
            </Button>
          </div>
        </div>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {!isLoading && appointments.length === 0 && !adding && (
        <p className="text-sm text-muted-foreground">No appointments booked.</p>
      )}
      <div className="space-y-2">
        {[...upcoming, ...other].map((a) => {
          const isUpcoming = upcoming.includes(a)
          return (
            <div
              key={a.id}
              className={cn('flex items-start justify-between gap-3 rounded-lg border px-3 py-2', !isUpcoming && 'opacity-60')}
              data-testid="appointment-row"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{a.title}</p>
                <p className="text-xs text-muted-foreground">
                  {formatDateTime(a.starts_at)}
                  {a.location ? ` · ${a.location}` : ''}
                </p>
                {a.notes && <p className="mt-0.5 text-xs">{a.notes}</p>}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                {a.status === 'CANCELLED' ? (
                  <Badge variant="secondary">Cancelled</Badge>
                ) : isUpcoming ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    disabled={cancel.isPending}
                    onClick={() => cancel.mutate(a.id)}
                    aria-label={`Cancel ${a.title}`}
                  >
                    <X className="h-4 w-4" />
                    Cancel
                  </Button>
                ) : (
                  <Badge variant="outline">Past</Badge>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
