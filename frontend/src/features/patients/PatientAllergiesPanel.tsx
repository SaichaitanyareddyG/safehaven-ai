import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { createAllergy, deleteAllergy, listAllergies } from '@/api/allergies'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ApiError } from '@/lib/api-client'

export function PatientAllergiesPanel({ patientId }: { patientId: string }) {
  const [newAllergen, setNewAllergen] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['patient-allergies', patientId],
    queryFn: () => listAllergies(patientId),
  })

  const createMutation = useMutation({
    mutationFn: (allergen: string) => createAllergy(patientId, allergen),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-allergies', patientId] })
      setNewAllergen('')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to add allergy')
    },
  })

  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const deleteMutation = useMutation({
    mutationFn: (allergyId: string) => deleteAllergy(patientId, allergyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient-allergies', patientId] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to remove allergy')
    },
  })

  function handleAdd() {
    const trimmed = newAllergen.trim()
    if (!trimmed) return
    createMutation.mutate(trimmed)
  }

  return (
    <div className="space-y-3" data-testid="allergies-panel">
      <p className="text-sm font-medium">Allergies</p>
      <p className="text-xs text-muted-foreground">
        Checked before every medication scan — a match stops the medicine being given, whatever the dose or time.
      </p>

      <div className="flex flex-wrap gap-2" data-testid="allergies-list">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {data && data.results.length === 0 && (
          <p className="text-sm text-muted-foreground">No known allergies documented.</p>
        )}
        {data?.results.map((allergy) => (
          <Badge
            key={allergy.id}
            variant="destructive"
            className="gap-1 py-1 pr-1"
            data-testid="allergy-badge"
          >
            {allergy.allergen}
            {confirmingId === allergy.id ? (
              <span className="ml-1 flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => {
                    setConfirmingId(null)
                    deleteMutation.mutate(allergy.id)
                  }}
                  disabled={deleteMutation.isPending}
                  className="rounded-md bg-background/90 px-2 py-1 text-xs font-semibold text-foreground"
                  data-testid="allergy-remove-confirm"
                >
                  Remove
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmingId(null)}
                  className="rounded-md px-2 py-1 text-xs font-medium underline-offset-2 hover:underline"
                >
                  Keep
                </button>
              </span>
            ) : (
              // Two taps, with a real target: removing an allergy changes what
              // the medication check blocks, so a stray tap must not do it.
              <button
                type="button"
                onClick={() => setConfirmingId(allergy.id)}
                className="flex size-7 items-center justify-center rounded-full hover:bg-black/10"
                aria-label={`Remove ${allergy.allergen}`}
                data-testid="allergy-remove-button"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </Badge>
        ))}
      </div>

      <div className="flex gap-2">
        <Input
          placeholder="e.g. Penicillin"
          value={newAllergen}
          onChange={(e) => setNewAllergen(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              handleAdd()
            }
          }}
          data-testid="allergy-input"
        />
        <Button
          variant="outline"
          size="sm"
          onClick={handleAdd}
          disabled={createMutation.isPending || !newAllergen.trim()}
          data-testid="allergy-add-button"
        >
          <Plus className="h-4 w-4" />
          Add
        </Button>
      </div>
    </div>
  )
}
