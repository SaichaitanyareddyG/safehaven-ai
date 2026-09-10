import { Check, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

const STEP_DURATION_MS = 700
const HOLD_AFTER_DONE_MS = 500

interface AiProcessingOverlayProps {
  title: string
  steps: string[]
  active: boolean
}

/**
 * A visual step-by-step progress display shown while an AI pipeline call
 * (analyze / generate) is in flight. The steps are paced client-side to
 * roughly match real latency, but never claim to be "done" ahead of the
 * actual API response — if the response takes longer than the simulated
 * pace, this holds on the last step (still spinning) rather than finishing
 * early. If the response comes back before the pace finishes, it jumps
 * straight to "all complete" rather than dragging out the animation.
 */
export function AiProcessingOverlay({ title, steps, active }: AiProcessingOverlayProps) {
  const [visible, setVisible] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [done, setDone] = useState(false)
  const wasActiveRef = useRef(false)

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | undefined
    let hideTimeout: ReturnType<typeof setTimeout> | undefined

    if (active) {
      setVisible(true)
      setDone(false)
      setCurrentStep(0)
      interval = setInterval(() => {
        setCurrentStep((step) => Math.min(step + 1, steps.length - 1))
      }, STEP_DURATION_MS)
    } else if (wasActiveRef.current) {
      setCurrentStep(steps.length - 1)
      setDone(true)
      hideTimeout = setTimeout(() => setVisible(false), HOLD_AFTER_DONE_MS)
    }
    wasActiveRef.current = active

    return () => {
      if (interval) clearInterval(interval)
      if (hideTimeout) clearTimeout(hideTimeout)
    }
  }, [active, steps.length])

  if (!visible) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm"
      data-testid="ai-processing-overlay"
    >
      <div className="w-full max-w-sm rounded-2xl border-2 bg-background p-6 shadow-lg">
        <p className="mb-4 text-center text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {title}
        </p>
        <ol className="space-y-3">
          {steps.map((step, index) => {
            const isComplete = done || index < currentStep
            const isActive = !done && index === currentStep
            const status = isComplete ? 'complete' : isActive ? 'active' : 'pending'
            return (
              <li
                key={step}
                className="flex items-center gap-3 text-sm"
                data-testid="ai-processing-step"
                data-status={status}
              >
                <span
                  className={cn(
                    'flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors',
                    isComplete && 'border-primary bg-primary text-primary-foreground',
                    isActive && 'border-primary text-primary',
                    status === 'pending' && 'border-border text-muted-foreground',
                  )}
                >
                  {isComplete ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : isActive ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <span className="h-1.5 w-1.5 rounded-full bg-current" />
                  )}
                </span>
                <span
                  className={cn(
                    isComplete && 'text-foreground',
                    isActive && 'font-medium text-foreground',
                    status === 'pending' && 'text-muted-foreground',
                  )}
                >
                  {step}
                </span>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}
