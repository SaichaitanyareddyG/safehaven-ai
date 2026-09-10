import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { createCondition, deleteCondition, listConditions } from '@/api/conditions'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api-client'

export function PatientConditionsPanel({ patientId }: { patientId: string }) {
  const [newCondition, setNewCondition] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['patient-conditions', patientId],
    queryFn: () => listConditions(patientId),
  })

  const createMutation = useMutation({
    mutationFn: (conditionName: string) => createCondition(patientId, conditionName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-conditions', patientId] })
      setNewCondition('')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add condition')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (conditionId: string) => deleteCondition(patientId, conditionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-conditions', patientId] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to remove condition')
    },
  })

  function handleAdd() {
    const trimmed = newCondition.trim()
    if (!trimmed) return
    createMutation.mutate(trimmed)
  }

  return (
    <div className="space-y-3" data-testid="conditions-panel">
      <p className="text-sm font-medium">Documented conditions</p>
      <p className="text-xs text-muted-foreground">
        Clinician-entered context only — not linked to specific instructions yet, and never used to
        guess a medication's purpose for this patient.
      </p>

      <div className="flex flex-wrap gap-2" data-testid="conditions-list">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {data && data.results.length === 0 && (
          <p className="text-sm text-muted-foreground">No conditions documented yet.</p>
        )}
        {data?.results.map((condition) => (
          <Badge key={condition.id} variant="secondary" className="gap-1 py-1 pr-1" data-testid="condition-badge">
            {condition.condition_name}
            <button
              type="button"
              onClick={() => deleteMutation.mutate(condition.id)}
              disabled={deleteMutation.isPending}
              className="rounded-full p-0.5 hover:bg-muted-foreground/20"
              aria-label={`Remove ${condition.condition_name}`}
              data-testid="condition-remove-button"
            >
              <X className="h-3 w-3" />
            </button>
          </Badge>
        ))}
      </div>

      <div className="flex gap-2">
        <Input
          placeholder="e.g. Hypertension"
          value={newCondition}
          onChange={(e) => setNewCondition(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleAdd()
            }
          }}
          data-testid="condition-input"
        />
        <Button
          variant="outline"
          size="sm"
          onClick={handleAdd}
          disabled={createMutation.isPending || !newCondition.trim()}
          data-testid="condition-add-button"
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>
    </div>
  )
}
