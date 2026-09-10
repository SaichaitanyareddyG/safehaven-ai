import { BrowserQRCodeReader } from '@zxing/browser'
import type { IScannerControls } from '@zxing/browser'
import { useEffect, useRef, useState } from 'react'

/**
 * One reusable camera-scan component, used for both the patient wristband
 * and the medication label — Module 2 uses QR codes for both scan targets
 * (see MODULE_2_DESIGN_REPORT.md section 7: one library, one format is the
 * simplest reliable prototype approach).
 */
export function BarcodeScanner({ onDecode }: { onDecode: (text: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const reader = new BrowserQRCodeReader()
    let controls: IScannerControls | undefined
    let stopped = false

    reader
      .decodeFromVideoDevice(undefined, videoRef.current ?? undefined, (result, _err, ctrl) => {
        controls = ctrl
        if (result && !stopped) {
          stopped = true
          ctrl.stop()
          onDecode(result.getText())
        }
      })
      .catch(() => {
        setError('Camera unavailable — check browser permissions.')
      })

    return () => {
      stopped = true
      controls?.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) {
    return <p className="text-sm text-destructive" data-testid="scanner-error">{error}</p>
  }

  return (
    <video
      ref={videoRef}
      className="aspect-video w-full rounded-lg border bg-black object-cover"
      data-testid="barcode-scanner-video"
      muted
      playsInline
    />
  )
}
