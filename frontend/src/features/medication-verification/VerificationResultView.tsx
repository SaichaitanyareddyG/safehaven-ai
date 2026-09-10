import { AlertTriangle, Camera, CheckCircle2, HelpCircle, XCircle } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { VerifyResponse } from '@/types/medication-verification'

const CHECK_LABELS: Record<string, string> = {
  patient: 'Patient',
  medication: 'Medication',
  order_status: 'Order Status',
  dose: 'Dose',
  formulation: 'Formulation',
  route: 'Route',
  time: 'Time',
}

const CHECK_ORDER = ['patient', 'medication', 'order_status', 'dose', 'formulation', 'route', 'time']

const RESULT_STYLES: Record<VerifyResponse['result'], { banner: string; label: string }> = {
  VERIFIED: { banner: 'border-green-500 bg-green-50 text-green-900', label: 'VERIFIED' },
  WARNING: { banner: 'border-amber-500 bg-amber-50 text-amber-900', label: 'WARNING' },
  REVIEW_REQUIRED: { banner: 'border-blue-500 bg-blue-50 text-blue-900', label: 'REVIEW REQUIRED' },
  BLOCKED: { banner: 'border-destructive bg-destructive/10 text-destructive', label: 'BLOCKED — DO NOT ADMINISTER' },
}

export function VerificationResultView({
  verification,
  onConfirm,
  onRescan,
  isAdministering,
}: {
  verification: VerifyResponse
  onConfirm: () => void
  onRescan: () => void
  isAdministering: boolean
}) {
  const style = RESULT_STYLES[verification.result]
  const rows = CHECK_ORDER.filter((key) => verification.checks[key])

  return (
    <div className="space-y-4" data-testid="verification-result">
      {verification.identification_method === 'IMAGE' && (
        <div className="flex items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" data-testid="image-identification-disclosure">
          <Camera className="h-4 w-4 shrink-0" />
          Barcode verification unavailable. Medication was identified from a label photo and manually confirmed.
        </div>
      )}

      {verification.product && (
        <div className="rounded-lg border bg-muted/30 p-3 text-sm">
          <p className="font-semibold">{verification.product.medication_name}</p>
          <p className="text-muted-foreground">
            {verification.product.strength_value}
            {verification.product.strength_unit} · {verification.product.formulation} · {verification.product.route}
          </p>
        </div>
      )}

      <div className="divide-y rounded-lg border">
        {rows.map((key) => {
          const check = verification.checks[key]
          return (
            <div key={key} className="flex items-start gap-3 p-3" data-testid="verification-check-row">
              {check.passed ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green-600" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              )}
              <div>
                <p className="text-sm font-medium">{CHECK_LABELS[key] ?? key}</p>
                <p className="text-sm text-muted-foreground">{check.detail}</p>
              </div>
            </div>
          )
        })}
      </div>

      <div className={cn('flex items-center gap-2 rounded-lg border-2 p-4 text-lg font-bold', style.banner)} data-testid="verification-banner">
        {verification.result === 'VERIFIED' && <CheckCircle2 className="h-5 w-5" />}
        {verification.result === 'WARNING' && <AlertTriangle className="h-5 w-5" />}
        {verification.result === 'REVIEW_REQUIRED' && <HelpCircle className="h-5 w-5" />}
        {verification.result === 'BLOCKED' && <XCircle className="h-5 w-5" />}
        {style.label}
      </div>

      <div className="flex gap-2">
        {(verification.result === 'VERIFIED' || verification.result === 'WARNING') && (
          <Button onClick={onConfirm} disabled={isAdministering} data-testid="confirm-administration-button">
            {verification.result === 'WARNING' ? 'Acknowledge & Confirm' : 'Confirm Administration'}
          </Button>
        )}
        <Button variant="outline" onClick={onRescan} data-testid="rescan-button">
          Rescan
        </Button>
      </div>
    </div>
  )
}
