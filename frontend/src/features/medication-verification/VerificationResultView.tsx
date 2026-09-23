import { AlertTriangle, Camera, CheckCircle2, HelpCircle, ShieldAlert, XCircle } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import type { NotGivenReason, VerifyResponse } from '@/types/medication-verification'

const CHECK_LABELS: Record<string, string> = {
  patient: 'Patient',
  admission: 'Admission',
  medication: 'Medication',
  allergy: 'Allergy',
  nil_by_mouth: 'Nil by Mouth',
  order_status: 'Order Status',
  dose: 'Dose',
  formulation: 'Formulation',
  route: 'Route',
  time: 'Time',
  interactions: 'Drug Interactions',
}

const CHECK_ORDER = [
  'patient',
  'admission',
  'medication',
  'allergy',
  'nil_by_mouth',
  'order_status',
  'dose',
  'formulation',
  'route',
  'time',
  'interactions',
]

const RESULT_STYLES: Record<VerifyResponse['result'], { banner: string; label: string }> = {
  VERIFIED: { banner: 'border-green-500 bg-green-50 text-green-900', label: 'VERIFIED' },
  WARNING: { banner: 'border-amber-500 bg-amber-50 text-amber-900', label: 'WARNING' },
  REVIEW_REQUIRED: { banner: 'border-blue-500 bg-blue-50 text-blue-900', label: 'REVIEW REQUIRED' },
  BLOCKED: { banner: 'border-destructive bg-destructive/10 text-destructive', label: 'BLOCKED — DO NOT ADMINISTER' },
}

// A dose can fail to happen for ordinary clinical reasons. Before this the
// nurse's only options were to give it or walk away — and walking away left a
// row indistinguishable from an interrupted scan.
const NOT_GIVEN_OPTIONS: { value: NotGivenReason; label: string }[] = [
  { value: 'REFUSED', label: 'Patient refused' },
  { value: 'HELD', label: 'Held (clinical decision)' },
  { value: 'PATIENT_UNAVAILABLE', label: 'Patient unavailable' },
  { value: 'VOMITED', label: 'Vomited' },
  { value: 'OTHER', label: 'Other' },
]

export function VerificationResultView({
  verification,
  onConfirm,
  onRescan,
  onNotGiven,
  isAdministering,
}: {
  verification: VerifyResponse
  onConfirm: (coSigner?: { email: string; password: string }, administrationReason?: string) => void
  onRescan: () => void
  onNotGiven: (reason: NotGivenReason, note?: string) => void
  isAdministering: boolean
}) {
  const [notGivenOpen, setNotGivenOpen] = useState(false)
  const [notGivenReason, setNotGivenReason] = useState<NotGivenReason>('REFUSED')
  const [notGivenNote, setNotGivenNote] = useState('')
  const style = RESULT_STYLES[verification.result]
  const rows = CHECK_ORDER.filter((key) => verification.checks[key])
  const isHighAlert = verification.product?.high_alert ?? false
  const isPrn = verification.order_is_prn
  const [coSignerEmail, setCoSignerEmail] = useState('')
  const [coSignerPassword, setCoSignerPassword] = useState('')
  const [administrationReason, setAdministrationReason] = useState('')
  const coSignReady = !isHighAlert || (coSignerEmail.trim() !== '' && coSignerPassword !== '')
  const reasonReady = !isPrn || administrationReason.trim() !== ''

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

      {isPrn && (verification.result === 'VERIFIED' || verification.result === 'WARNING') && (
        <div className="space-y-2 rounded-lg border bg-muted/30 p-4" data-testid="prn-reason-panel">
          <Label htmlFor="administration-reason">
            As-needed (PRN) medication — why is it being given?
          </Label>
          <Input
            id="administration-reason"
            placeholder="e.g. pain 7/10"
            value={administrationReason}
            onChange={(e) => setAdministrationReason(e.target.value)}
            data-testid="administration-reason-input"
          />
          <p className="text-xs text-muted-foreground">
            Recorded with the dose so the next clinician can tell whether it helped.
          </p>
        </div>
      )}

      {isHighAlert && (verification.result === 'VERIFIED' || verification.result === 'WARNING') && (
        <div
          className="space-y-3 rounded-lg border-2 border-amber-400 bg-amber-50 p-4 text-amber-900"
          data-testid="high-alert-cosign-panel"
        >
          <p className="flex items-center gap-2 text-sm font-semibold">
            <ShieldAlert className="h-4 w-4 shrink-0" />
            High-alert medication — a second clinician must independently co-sign before administration.
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="co-signer-email">Co-signer email</Label>
              <Input
                id="co-signer-email"
                type="email"
                value={coSignerEmail}
                onChange={(e) => setCoSignerEmail(e.target.value)}
                data-testid="co-signer-email-input"
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="co-signer-password">Co-signer password</Label>
              <Input
                id="co-signer-password"
                type="password"
                value={coSignerPassword}
                onChange={(e) => setCoSignerPassword(e.target.value)}
                data-testid="co-signer-password-input"
              />
            </div>
          </div>
        </div>
      )}

      <div className="flex gap-2">
        {(verification.result === 'VERIFIED' || verification.result === 'WARNING') && (
          <Button
            onClick={() =>
              onConfirm(
                isHighAlert ? { email: coSignerEmail, password: coSignerPassword } : undefined,
                isPrn ? administrationReason : undefined,
              )
            }
            disabled={isAdministering || !coSignReady || !reasonReady}
            data-testid="confirm-administration-button"
          >
            {verification.result === 'WARNING' ? 'Acknowledge & Confirm' : 'Confirm Administration'}
          </Button>
        )}
        <Button variant="outline" onClick={onRescan} data-testid="rescan-button">
          Rescan
        </Button>
        {!notGivenOpen && (
          <Button variant="outline" onClick={() => setNotGivenOpen(true)} data-testid="not-given-button">
            Not given
          </Button>
        )}
      </div>

      {notGivenOpen && (
        <div className="space-y-3 rounded-lg border p-4" data-testid="not-given-panel">
          <Label htmlFor="not-given-reason">Why was this dose not given?</Label>
          <select
            id="not-given-reason"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            value={notGivenReason}
            onChange={(e) => setNotGivenReason(e.target.value as NotGivenReason)}
            data-testid="not-given-reason-select"
          >
            {NOT_GIVEN_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <Input
            placeholder="Anything worth noting (optional)"
            value={notGivenNote}
            onChange={(e) => setNotGivenNote(e.target.value)}
            data-testid="not-given-note-input"
          />
          <div className="flex gap-2">
            <Button
              onClick={() => onNotGiven(notGivenReason, notGivenNote.trim() || undefined)}
              disabled={isAdministering}
              data-testid="not-given-submit"
            >
              Record
            </Button>
            <Button variant="ghost" onClick={() => setNotGivenOpen(false)} data-testid="not-given-cancel">
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
