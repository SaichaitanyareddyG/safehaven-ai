import { useMutation } from '@tanstack/react-query'
import { Camera, CameraOff, QrCode, UserRound } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { resolveWearableQr } from '@/api/safety-monitoring'
import { AppLayout } from '@/components/AppLayout'
import { BarcodeScanner } from '@/components/BarcodeScanner'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api-client'

const PROFILE_LABEL: Record<string, string> = {
  STANDARD: 'Standard',
  FALL_RISK: 'Fall risk',
  RESTRICTED_MOBILITY: 'Restricted mobility',
}

/**
 * Scan a wearable's QR to see which patient wears it.
 *
 * The QR carries an opaque token (plan §11) — meaningless to anyone without a
 * clinician session — so the lookup happens server-side and is audited. The
 * result is an AUXILIARY identifier: the hospital wristband stays the
 * authority for any clinical action.
 */
export function ScanBandPage() {
  const [cameraOn, setCameraOn] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [manual, setManual] = useState('')

  const resolve = useMutation({ mutationFn: resolveWearableQr })

  function startCamera() {
    setCameraError(null)
    resolve.reset()
    setCameraOn(true)
  }

  // The same QR reader as the medication check (works in Safari too).
  function onDecode(text: string) {
    setCameraOn(false)
    if (text.startsWith('SH:')) resolve.mutate(text)
    else setCameraError("That QR code isn't from a SafeHaven band.")
  }

  const notFound = resolve.error instanceof ApiError && resolve.error.status === 404
  const result = resolve.data

  return (
    <AppLayout>
      <div className="mx-auto max-w-xl space-y-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Scan a wearable</h1>
          <p className="text-sm text-muted-foreground">
            Point the camera at the QR code on a SAFEHAVEN band to see which patient is wearing it.
          </p>
        </div>

        <Card>
          <CardContent className="space-y-4 pt-6">
            {cameraOn ? (
              <>
                <BarcodeScanner
                  onDecode={onDecode}
                  onError={() => {
                    setCameraOn(false)
                    setCameraError('Camera unavailable — allow camera access for this site, or paste the code below.')
                  }}
                />
                <Button variant="outline" onClick={() => setCameraOn(false)} className="w-full">
                  <CameraOff className="h-4 w-4" />
                  Stop camera
                </Button>
              </>
            ) : (
              <Button onClick={startCamera} className="w-full" data-testid="start-scan">
                <Camera className="h-4 w-4" />
                Scan with camera
              </Button>
            )}
            {cameraError && <p className="text-sm text-destructive">{cameraError}</p>}

            <form
              className="space-y-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (manual.trim()) resolve.mutate(manual.trim())
              }}
            >
              <Label htmlFor="band-code">Or paste the scanned code</Label>
              <div className="flex gap-2">
                <Input
                  id="band-code"
                  value={manual}
                  onChange={(e) => setManual(e.target.value)}
                  placeholder="SH:…"
                  autoComplete="off"
                />
                <Button type="submit" variant="outline" disabled={!manual.trim() || resolve.isPending}>
                  <QrCode className="h-4 w-4" />
                  Look up
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        {notFound && (
          <Alert variant="destructive">
            <AlertTitle>No patient found for this code</AlertTitle>
            <AlertDescription>
              Either the band isn't assigned to anyone right now (its code stops working when monitoring ends), or
              the code was mistyped. Check the band, or find the patient on the Patients page.
            </AlertDescription>
          </Alert>
        )}
        {resolve.isError && !notFound && (
          <Alert variant="destructive">
            <AlertTitle>Could not look up the band</AlertTitle>
            <AlertDescription>
              {resolve.error instanceof Error ? resolve.error.message : 'Unknown error'}
            </AlertDescription>
          </Alert>
        )}

        {result && (
          <Card data-testid="scan-result">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <UserRound className="h-5 w-5" />
                {result.patient_name}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <dl className="grid grid-cols-2 gap-y-1">
                <dt className="text-muted-foreground">Patient code</dt>
                <dd>{result.patient_code}</dd>
                <dt className="text-muted-foreground">Room</dt>
                <dd>{result.room_number ?? 'Not recorded'}</dd>
                <dt className="text-muted-foreground">Band</dt>
                <dd>{result.device_code}</dd>
                <dt className="text-muted-foreground">Monitoring</dt>
                <dd>{PROFILE_LABEL[result.monitoring_profile] ?? result.monitoring_profile}</dd>
              </dl>
              <Alert>
                <AlertDescription>
                  Confirm identity with the hospital wristband before any clinical action. The band's QR
                  helps you find the patient; it is not an identifier on its own.
                </AlertDescription>
              </Alert>
              <Link to={`/patients/${result.patient_id}`}>
                <Button className="w-full">Open patient</Button>
              </Link>
            </CardContent>
          </Card>
        )}
      </div>
    </AppLayout>
  )
}
