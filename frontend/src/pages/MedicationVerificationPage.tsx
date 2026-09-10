import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { administerMedication, verifyConfirmedMedication, verifyMedication } from '@/api/medication-verification'
import { getPatientByCode } from '@/api/patients'
import { AppLayout } from '@/components/AppLayout'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ImageFallbackStep } from '@/features/medication-verification/ImageFallbackStep'
import { ScanOrManualEntry } from '@/features/medication-verification/ScanOrManualEntry'
import { VerificationResultView } from '@/features/medication-verification/VerificationResultView'
import { ApiError } from '@/lib/api-client'
import type { Patient } from '@/types/patients'
import type { ConfirmedProductCandidate, VerifyResponse } from '@/types/medication-verification'

type Step = 'scan-patient' | 'scan-medication' | 'result' | 'administered'

export function MedicationVerificationPage() {
  const [step, setStep] = useState<Step>('scan-patient')
  const [patient, setPatient] = useState<Patient | null>(null)
  const [verification, setVerification] = useState<VerifyResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [administerError, setAdministerError] = useState<string | null>(null)

  const patientScanMutation = useMutation({
    mutationFn: (code: string) => getPatientByCode(code),
    onSuccess: (resolved) => {
      setPatient(resolved)
      setError(null)
      setStep('scan-medication')
    },
    onError: (err) => {
      setError(err instanceof ApiError && err.status === 404 ? 'Unknown patient wristband — please rescan.' : 'Could not read wristband — please rescan.')
    },
  })

  const verifyMutation = useMutation({
    mutationFn: (barcode: string) => verifyMedication(patient!.patient_code, barcode),
    onSuccess: (result) => {
      setVerification(result)
      setError(null)
      setStep('result')
    },
    onError: () => setError('Could not verify this scan — please rescan.'),
  })

  const verifyConfirmedMutation = useMutation({
    mutationFn: (candidate: ConfirmedProductCandidate) => verifyConfirmedMedication(patient!.patient_code, candidate),
    onSuccess: (result) => {
      setVerification(result)
      setError(null)
      setStep('result')
    },
    onError: () => setError('Could not verify the confirmed medication — please try again.'),
  })

  const administerMutation = useMutation({
    mutationFn: () => administerMedication(verification!.id),
    onSuccess: () => {
      setAdministerError(null)
      setStep('administered')
    },
    onError: (err) => {
      // The backend revalidates the order and checks for a duplicate
      // administration right before recording anything — its rejection
      // message (e.g. "the order is no longer active", "already
      // administered at ...") is written to be shown to the nurse directly,
      // not paraphrased away.
      setAdministerError(
        err instanceof ApiError ? err.message : 'Could not confirm administration — please rescan and try again.',
      )
    },
  })

  function reset() {
    setStep('scan-patient')
    setPatient(null)
    setVerification(null)
    setError(null)
    setAdministerError(null)
  }

  function rescanMedication() {
    setVerification(null)
    setError(null)
    setAdministerError(null)
    setStep('scan-medication')
  }

  return (
    <AppLayout>
      <div className="mx-auto max-w-lg">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-bold tracking-tight">Medication Verification</h1>
          {step !== 'scan-patient' && (
            <Button variant="ghost" size="sm" onClick={reset} data-testid="start-over-button">
              <RotateCcw className="h-4 w-4" />
              Start over
            </Button>
          )}
        </div>

        {patient && step !== 'scan-patient' && (
          <Card className="mb-4">
            <CardContent className="flex items-center justify-between py-4">
              <div>
                <p className="font-semibold">
                  {patient.first_name} {patient.last_name}
                </p>
                <p className="text-sm text-muted-foreground">
                  {patient.patient_code}
                  {patient.room_number ? ` · Room ${patient.room_number}` : ''}
                </p>
              </div>
            </CardContent>
          </Card>
        )}

        {step === 'scan-patient' && (
          <Card>
            <CardHeader>
              <CardTitle>Step 1 — Identify Patient</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <ScanOrManualEntry
                testIdPrefix="patient-id"
                manualLabel="Enter Patient ID"
                manualPlaceholder="e.g. P1001"
                onSubmit={(code) => patientScanMutation.mutate(code)}
                isPending={patientScanMutation.isPending}
              />
              {patientScanMutation.isPending && <p className="text-sm text-muted-foreground">Looking up patient…</p>}
              {error && <p className="text-sm text-destructive">{error}</p>}
            </CardContent>
          </Card>
        )}

        {step === 'scan-medication' && patient && (
          <Card>
            <CardHeader>
              <CardTitle>Step 2 — Scan Medication</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <ScanOrManualEntry
                testIdPrefix="medication-id"
                manualLabel="Enter Barcode"
                manualPlaceholder="e.g. MED-METOPROLOL-SUCCINATE-25"
                onSubmit={(barcode) => verifyMutation.mutate(barcode)}
                isPending={verifyMutation.isPending}
              />
              {verifyMutation.isPending && <p className="text-sm text-muted-foreground">Verifying…</p>}
              {error && <p className="text-sm text-destructive">{error}</p>}

              <ImageFallbackStep
                patientId={patient.id}
                onConfirm={(candidate) => verifyConfirmedMutation.mutate(candidate)}
                isSubmitting={verifyConfirmedMutation.isPending}
              />
            </CardContent>
          </Card>
        )}

        {step === 'result' && verification && (
          <Card>
            <CardHeader>
              <CardTitle>Verification</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <VerificationResultView
                verification={verification}
                onConfirm={() => administerMutation.mutate()}
                onRescan={rescanMedication}
                isAdministering={administerMutation.isPending}
              />
              {administerError && (
                <p className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive" data-testid="administer-error">
                  {administerError}
                </p>
              )}
            </CardContent>
          </Card>
        )}

        {step === 'administered' && (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
              <CheckCircle2 className="h-10 w-10 text-green-600" />
              <p className="text-lg font-semibold">Administration confirmed</p>
              <p className="text-sm text-muted-foreground">{new Date().toLocaleString()}</p>
              <Button onClick={reset} data-testid="verify-another-button">
                Verify another medication
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </AppLayout>
  )
}
