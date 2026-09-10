import { Keyboard, ScanLine } from 'lucide-react'
import { useState } from 'react'

import { BarcodeScanner } from '@/components/BarcodeScanner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

type Mode = 'scan' | 'enter'

/**
 * Generic scan-or-type-it-in toggle, used for both patient identification
 * (wristband QR vs. patient ID) and medication identification (barcode QR
 * vs. the barcode string itself) — same pattern, same component, just
 * different labels/placeholder. Both are equally valid, optional paths; a
 * camera isn't always practical (desktop testing, no label printed yet).
 */
export function ScanOrManualEntry({
  onSubmit,
  isPending,
  testIdPrefix,
  manualLabel,
  manualPlaceholder,
}: {
  onSubmit: (value: string) => void
  isPending: boolean
  testIdPrefix: string
  manualLabel: string
  manualPlaceholder: string
}) {
  const [mode, setMode] = useState<Mode>('scan')
  const [manualValue, setManualValue] = useState('')

  function handleManualSubmit() {
    const value = manualValue.trim()
    if (value) onSubmit(value)
  }

  return (
    <div className="space-y-3">
      <div className="inline-flex rounded-lg border p-1" role="tablist">
        <button
          type="button"
          onClick={() => setMode('scan')}
          className={cn(
            'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'scan' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted',
          )}
          data-testid={`${testIdPrefix}-mode-scan`}
        >
          <ScanLine className="h-4 w-4" />
          Scan
        </button>
        <button
          type="button"
          onClick={() => setMode('enter')}
          className={cn(
            'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
            mode === 'enter' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted',
          )}
          data-testid={`${testIdPrefix}-mode-enter`}
        >
          <Keyboard className="h-4 w-4" />
          {manualLabel}
        </button>
      </div>

      {mode === 'scan' ? (
        <BarcodeScanner onDecode={onSubmit} />
      ) : (
        <div className="flex gap-2">
          <Input
            value={manualValue}
            onChange={(e) => setManualValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleManualSubmit()}
            placeholder={manualPlaceholder}
            disabled={isPending}
            data-testid={`${testIdPrefix}-manual-input`}
          />
          <Button onClick={handleManualSubmit} disabled={isPending || !manualValue.trim()} data-testid={`${testIdPrefix}-manual-submit`}>
            Look up
          </Button>
        </div>
      )}
    </div>
  )
}
