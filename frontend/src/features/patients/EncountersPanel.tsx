import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { createEncounter, listEncounters, updateEncounter } from '@/api/encounters'
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

  const openEncounter = data?.results.find((e) => e.status === 'OPEN')
  const [procedure, setProcedure] = useState('')
  const [npoFrom, setNpoFrom] = useState('')

  // Prefill from the open visit once it loads, and again if it changes, so the
  // form shows what is currently recorded rather than blanks over real values.
  // <input type="datetime-local"> wants "YYYY-MM-DDTHH:mm"; the API returns a
  // full ISO timestamp.
  useEffect(() => {
    setProcedure(openEncounter?.planned_procedure ?? '')
    setNpoFrom(openEncounter?.nil_by_mouth_from?.slice(0, 16) ?? '')
  }, [openEncounter?.id, openEncounter?.planned_procedure, openEncounter?.nil_by_mouth_from])

  const npoMutation = useMutation({
    mutationFn: (payload: { planned_procedure: string | null; nil_by_mouth_from: string }) =>
      updateEncounter(openEncounter!.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-encounters', patientId] })
      toast.success('Visit updated')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to update the visit')
    },
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
            <div className="flex items-center gap-2">
              {encounter.nil_by_mouth_from && (
                <Badge
                  variant="outline"
                  className="border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
                  data-testid="encounter-npo-badge"
                >
                  Nil by mouth
                </Badge>
              )}
              <Badge variant={encounter.status === 'OPEN' ? 'default' : 'secondary'} data-status={encounter.status}>
                {encounter.status}
              </Badge>
            </div>
          </div>
        ))}
      </div>

      {/* Procedure and nil-by-mouth are normally decided after admission, not at
          registration, so they are edited on the open visit rather than captured
          on the Add form.

          This is not cosmetic: nil_by_mouth_from is what Module 2's
          administration check reads to warn that an oral dose is being given to
          a patient who must not eat or drink. The backend field, endpoint and
          check already existed, but nothing in the UI could set it — so that
          safety check could never fire in practice. "Situational state is part
          of safety" (DOCUMENTATION.md §7 rule 8). */}
      {openEncounter && (
        <div className="space-y-2 rounded-lg border border-dashed p-3" data-testid="encounter-situational-state">
          <p className="text-xs font-medium">Current visit — pre-op / nil by mouth</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
            <div className="space-y-1">
              <Label htmlFor="encounter-procedure" className="text-xs">
                Planned procedure
              </Label>
              <Input
                id="encounter-procedure"
                placeholder="e.g. Hip replacement"
                value={procedure}
                onChange={(e) => setProcedure(e.target.value)}
                data-testid="encounter-procedure-input"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="encounter-npo" className="text-xs">
                Nil by mouth from
              </Label>
              <Input
                id="encounter-npo"
                type="datetime-local"
                value={npoFrom}
                onChange={(e) => setNpoFrom(e.target.value)}
                data-testid="encounter-npo-input"
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              className="self-end"
              onClick={() =>
                npoMutation.mutate({
                  planned_procedure: procedure.trim() || null,
                  nil_by_mouth_from: npoFrom,
                })
              }
              disabled={npoMutation.isPending}
              data-testid="encounter-npo-save"
            >
              Save
            </Button>
          </div>
        </div>
      )}

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
