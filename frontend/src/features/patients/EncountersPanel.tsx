import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { createEncounter, listEncounters } from '@/api/encounters'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api-client'

export function EncountersPanel({ patientId }: { patientId: string }) {
  const [reasonForVisit, setReasonForVisit] = useState('')
  const [admissionDate, setAdmissionDate] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['patient-encounters', patientId],
    queryFn: () => listEncounters(patientId),
  })

  const createMutation = useMutation({
    mutationFn: () => createEncounter(patientId, { reason_for_visit: reasonForVisit.trim(), admission_date: admissionDate }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-encounters', patientId] })
      setReasonForVisit('')
      setAdmissionDate('')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add encounter')
    },
  })

  function handleAdd() {
    if (!admissionDate) return
    createMutation.mutate()
  }

  return (
    <div className="space-y-3" data-testid="encounters-panel">
      <p className="text-sm font-medium">Encounters / Visits</p>
      <p className="text-xs text-muted-foreground">
        Each visit's diagnoses and medication orders stay scoped to that visit — never merged together across
        visits.
      </p>

      <div className="space-y-2" data-testid="encounters-list">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {data && data.results.length === 0 && <p className="text-sm text-muted-foreground">No encounters recorded yet.</p>}
        {data?.results.map((encounter) => (
          <div
            key={encounter.id}
            className="flex items-center justify-between rounded-lg border px-3 py-2"
            data-testid="encounter-row"
          >
            <div>
              <p className="text-sm font-medium">{encounter.reason_for_visit ?? 'Visit'}</p>
              <p className="text-xs text-muted-foreground">
                {encounter.admission_date}
                {encounter.discharge_date ? ` – ${encounter.discharge_date}` : ''}
              </p>
            </div>
            <Badge variant={encounter.status === 'OPEN' ? 'default' : 'secondary'} data-status={encounter.status}>
              {encounter.status}
            </Badge>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
        <div className="space-y-1">
          <Label htmlFor="encounter-reason" className="text-xs">
            Reason for visit
          </Label>
          <Input
            id="encounter-reason"
            placeholder="e.g. Hypertension follow-up"
            value={reasonForVisit}
            onChange={(e) => setReasonForVisit(e.target.value)}
            data-testid="encounter-reason-input"
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="encounter-date" className="text-xs">
            Admission date
          </Label>
          <Input
            id="encounter-date"
            type="date"
            value={admissionDate}
            onChange={(e) => setAdmissionDate(e.target.value)}
            data-testid="encounter-date-input"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          className="self-end"
          onClick={handleAdd}
          disabled={createMutation.isPending || !admissionDate}
          data-testid="encounter-add-button"
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>
    </div>
  )
}
