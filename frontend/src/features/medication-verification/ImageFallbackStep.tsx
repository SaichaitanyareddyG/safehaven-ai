import { useMutation } from '@tanstack/react-query'
import { AlertTriangle, Camera } from 'lucide-react'
import { useState } from 'react'

import { identifyMedicationFromImage } from '@/api/medication-verification'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ConfirmedProductCandidate } from '@/types/medication-verification'

/**
 * Barcode-failure fallback: photograph the label, get an UNCONFIRMED
 * candidate back, let the nurse review/correct every field, and only submit
 * on explicit confirmation. This never shows a verification result itself —
 * see MODULE_2_IMPLEMENTATION_PLAN.md section 8. The confirmed fields go
 * through the exact same deterministic engine as a barcode scan once
 * submitted (onConfirm), permanently marked as image-identified.
 */
export function ImageFallbackStep({
  patientId,
  onConfirm,
  isSubmitting,
}: {
  patientId: string
  onConfirm: (candidate: ConfirmedProductCandidate) => void
  isSubmitting: boolean
}) {
  const [candidate, setCandidate] = useState<ConfirmedProductCandidate | null>(null)
  const [confidence, setConfidence] = useState<'high' | 'low' | null>(null)

  const identifyMutation = useMutation({
    mutationFn: (file: File) => identifyMedicationFromImage(file, patientId),
    onSuccess: (result) => {
      setConfidence(result.confidence)
      setCandidate({
        medication_name: result.medication_name ?? '',
        strength_value: result.strength_value ?? 0,
        strength_unit: result.strength_unit ?? '',
        formulation: result.formulation ?? '',
        route: result.route ?? '',
      })
    },
  })

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) identifyMutation.mutate(file)
  }

  if (!candidate) {
    return (
      <div className="space-y-3 rounded-lg border border-dashed p-4 text-center">
        <p className="text-sm text-muted-foreground">
          Barcode won't scan? Photograph the medication label instead.
        </p>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground">
          <Camera className="h-4 w-4" />
          {identifyMutation.isPending ? 'Reading label…' : 'Photograph Label'}
          <input
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={handleFileChange}
            disabled={identifyMutation.isPending}
            data-testid="image-fallback-file-input"
          />
        </label>
      </div>
    )
  }

  return (
    <div className="space-y-3 rounded-lg border-2 border-amber-400 bg-amber-50 p-4" data-testid="image-fallback-candidate">
      <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
        <AlertTriangle className="h-4 w-4" />
        Barcode verification unavailable — please confirm what's on the label
      </div>
      {confidence === 'low' && (
        <p className="text-sm text-amber-800">
          Low confidence — the image may be unclear. Check each field carefully before confirming.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <Label htmlFor="candidate-name">Medication name</Label>
          <Input
            id="candidate-name"
            value={candidate.medication_name}
            onChange={(e) => setCandidate({ ...candidate, medication_name: e.target.value })}
            data-testid="candidate-medication-name"
          />
        </div>
        <div>
          <Label htmlFor="candidate-strength">Strength</Label>
          <Input
            id="candidate-strength"
            type="number"
            value={candidate.strength_value}
            onChange={(e) => setCandidate({ ...candidate, strength_value: Number(e.target.value) })}
            data-testid="candidate-strength-value"
          />
        </div>
        <div>
          <Label htmlFor="candidate-unit">Unit</Label>
          <Input
            id="candidate-unit"
            value={candidate.strength_unit}
            onChange={(e) => setCandidate({ ...candidate, strength_unit: e.target.value })}
            data-testid="candidate-strength-unit"
          />
        </div>
        <div className="col-span-2">
          <Label htmlFor="candidate-formulation">Formulation</Label>
          <Input
            id="candidate-formulation"
            value={candidate.formulation}
            onChange={(e) => setCandidate({ ...candidate, formulation: e.target.value })}
            data-testid="candidate-formulation"
          />
        </div>
        <div className="col-span-2">
          <Label htmlFor="candidate-route">Route</Label>
          <Input
            id="candidate-route"
            value={candidate.route}
            onChange={(e) => setCandidate({ ...candidate, route: e.target.value })}
            data-testid="candidate-route"
          />
        </div>
      </div>

      <div className="flex gap-2">
        <Button onClick={() => onConfirm(candidate)} disabled={isSubmitting} data-testid="confirm-candidate-button">
          Confirm
        </Button>
        <Button variant="outline" onClick={() => setCandidate(null)} disabled={isSubmitting} data-testid="incorrect-candidate-button">
          Incorrect / Retake Photo
        </Button>
      </div>
    </div>
  )
}
