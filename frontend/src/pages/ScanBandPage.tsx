import { useMutation } from '@tanstack/react-query'
import { Camera, CameraOff, QrCode, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { resolveWearableQr } from '@/api/safety-monitoring'
import { AppLayout } from '@/components/AppLayout'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api-client'

// The Shape Detection API: built into Chromium browsers, so no QR library is
// added (the repo's no-new-dependencies rule). Elsewhere, staff paste the code.
interface DetectedBarcode {
  rawValue: string
}
interface BarcodeDetectorLike {
  detect(source: CanvasImageSource): Promise<DetectedBarcode[]>
}
type BarcodeDetectorCtor = new (opts: { formats: string[] }) => BarcodeDetectorLike

function barcodeDetector(): BarcodeDetectorCtor | null {
  const ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
  return ctor ?? null
}

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
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [cameraOn, setCameraOn] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [manual, setManual] = useState('')

  const resolve = useMutation({ mutationFn: resolveWearableQr })
  const canScan = barcodeDetector() !== null && !!navigator.mediaDevices?.getUserMedia

  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setCameraOn(false)
  }

  async function startCamera() {
    setCameraError(null)
    resolve.reset()
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      streamRef.current = stream
      setCameraOn(true)
    } catch {
      setCameraError('Camera unavailable. Allow camera access for this site, or paste the code below.')
    }
  }

  // Attach the stream once the <video> exists, then scan a few times a second.
  useEffect(() => {
    if (!cameraOn || !videoRef.current || !streamRef.current) return
    const video = videoRef.current
    video.srcObject = streamRef.current
    void video.play()

    const Detector = barcodeDetector()
    if (!Detector) return
    const detector = new Detector({ formats: ['qr_code'] })
    let busy = false
    const timer = window.setInterval(async () => {
      if (busy || video.readyState < 2) return
      busy = true
      try {
        const codes = await detector.detect(video)
        const hit = codes.find((c) => c.rawValue.startsWith('SH:'))
        if (hit) {
          window.clearInterval(timer)
          streamRef.current?.getTracks().forEach((t) => t.stop())
          streamRef.current = null
          setCameraOn(false)
          resolve.mutate(hit.rawValue)
        }
      } finally {
        busy = false
      }
    }, 300)
    return () => window.clearInterval(timer)
  }, [cameraOn, resolve])

  useEffect(() => () => streamRef.current?.getTracks().forEach((t) => t.stop()), [])

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
                <video
                  ref={videoRef}
                  className="aspect-square w-full rounded-md bg-black object-cover"
                  muted
                  playsInline
                  aria-label="Camera preview for scanning the band's QR code"
                />
                <Button variant="outline" onClick={stopCamera} className="w-full">
                  <CameraOff className="h-4 w-4" />
                  Stop camera
                </Button>
              </>
            ) : (
              <Button onClick={startCamera} disabled={!canScan} className="w-full" data-testid="start-scan">
                <Camera className="h-4 w-4" />
                Scan with camera
              </Button>
            )}
            {!canScan && (
              <p className="text-sm text-muted-foreground">
                This browser cannot read QR codes from the camera. Use Chrome or Edge, or paste the code
                below.
              </p>
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
            <AlertTitle>Not assigned</AlertTitle>
            <AlertDescription>
              This band is not currently assigned to a patient. Its QR stops working as soon as monitoring
              ends.
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
