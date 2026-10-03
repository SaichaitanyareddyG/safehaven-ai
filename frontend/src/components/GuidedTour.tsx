import { X } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { completeTour } from '@/api/auth'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'

interface TourStep {
  /** The `data-tour` anchor to point at; none = a centred card. */
  target?: string
  title: string
  body: string
  adminOnly?: boolean
}

const STEPS: TourStep[] = [
  {
    title: 'Welcome to SafeHaven',
    body: "A quick look around the ward dashboard — under a minute. You can replay it any time from your name at the bottom of the menu.",
  },
  {
    target: 'alerts',
    title: 'Safety alerts',
    body: 'Falls, faints, help requests and band problems arrive here. You will hear a sound and see a pop-up on any page, so you never need to keep this open.',
  },
  {
    target: 'patients',
    title: 'Patients',
    body: 'Everyone on the ward, with care plans and medicines. Open a patient to give them a wrist band.',
  },
  {
    target: 'devices',
    title: 'Bands',
    body: 'Every wrist band, with battery and connection. Add a new band here using the code on its screen.',
  },
  {
    target: 'scan-band',
    title: 'Scan band',
    body: 'Point your camera at the QR code on a band to see who is wearing it.',
  },
  {
    target: 'medication',
    title: 'Medication check',
    body: 'Before giving a medicine, scan the patient and the pack. SafeHaven checks it is the right one, at the right time.',
  },
  {
    target: 'users',
    title: 'Users',
    body: 'Add staff, reset a forgotten password, or switch off an account when someone leaves. Only admins see this.',
    adminOnly: true,
  },
  {
    target: 'user-menu',
    title: 'Your menu',
    body: 'Change your password, replay this tour, or log out.',
  },
]

const CARD_WIDTH = 360
const GAP = 16
const PAD = 6

interface Box {
  top: number
  left: number
  width: number
  height: number
}

/**
 * The first-run guided tour: a dimmed screen with one menu item lit up at a
 * time and a card beside it explaining what it is for, like most apps show a
 * new user. Shown once per user (remembered on the server), replayable from
 * the user menu. When a step's item is not on screen (the phone menu is
 * folded away) the card simply shows in the middle.
 */
export function GuidedTour({ onClose }: { onClose: () => void }) {
  const { user, refreshUser } = useAuth()
  const steps = STEPS.filter((s) => !s.adminOnly || user?.role === 'admin')
  const [index, setIndex] = useState(0)
  const [spot, setSpot] = useState<Box | null>(null)
  const [cardPos, setCardPos] = useState<{ top: number; left: number } | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  const step = steps[index]
  const last = index === steps.length - 1

  const finish = useCallback(async () => {
    onClose()
    if (user && !user.tour_completed) {
      try {
        await completeTour()
        await refreshUser()
      } catch {
        // Not worth bothering anyone about: at worst the tour shows again.
      }
    }
  }, [onClose, user, refreshUser])

  const place = useCallback(() => {
    const el = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null
    const rect = el?.getBoundingClientRect()
    const card = cardRef.current?.getBoundingClientRect()
    const cardH = card?.height ?? 220
    const cardW = Math.min(CARD_WIDTH, window.innerWidth - 2 * GAP)

    if (!rect || rect.width === 0 || rect.height === 0) {
      setSpot(null)
      setCardPos({ top: Math.max(GAP, (window.innerHeight - cardH) / 2), left: (window.innerWidth - cardW) / 2 })
      return
    }
    setSpot({ top: rect.top - PAD, left: rect.left - PAD, width: rect.width + 2 * PAD, height: rect.height + 2 * PAD })

    const clampTop = (t: number) => Math.min(Math.max(GAP, t), window.innerHeight - cardH - GAP)
    if (rect.right + GAP + cardW <= window.innerWidth - GAP) {
      // Beside the menu item (the desktop side menu).
      setCardPos({ top: clampTop(rect.top - 8), left: rect.right + GAP })
    } else if (rect.bottom + GAP + cardH <= window.innerHeight) {
      setCardPos({ top: rect.bottom + GAP, left: Math.max(GAP, Math.min(rect.left, window.innerWidth - cardW - GAP)) })
    } else {
      setCardPos({ top: clampTop(rect.top - cardH - GAP), left: Math.max(GAP, Math.min(rect.left, window.innerWidth - cardW - GAP)) })
    }
  }, [step])

  useLayoutEffect(() => {
    place()
  }, [place])

  useEffect(() => {
    window.addEventListener('resize', place)
    return () => window.removeEventListener('resize', place)
  }, [place])

  // Move focus to the card each step, so keyboard and screen-reader users follow along.
  useEffect(() => {
    cardRef.current?.focus()
  }, [index])

  return (
    <div className="fixed inset-0 z-50" data-testid="guided-tour">
      {spot ? (
        <div
          aria-hidden="true"
          className="pointer-events-none fixed rounded-xl ring-3 ring-[#2EC4B6] transition-all duration-200"
          style={{ ...spot, boxShadow: '0 0 0 9999px rgba(6, 20, 19, 0.62)' }}
        />
      ) : (
        <div aria-hidden="true" className="fixed inset-0 bg-[#061413]/60" />
      )}

      <div
        ref={cardRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        tabIndex={-1}
        onKeyDown={(e) => {
          if (e.key === 'Escape') void finish()
        }}
        className={cn(
          'fixed flex flex-col gap-3 rounded-2xl bg-white p-6 text-[#0B0D0E] shadow-[0_24px_60px_rgba(0,0,0,0.35)] outline-none',
          !cardPos && 'invisible',
        )}
        style={{ top: cardPos?.top, left: cardPos?.left, width: Math.min(CARD_WIDTH, window.innerWidth - 2 * GAP) }}
      >
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-semibold tracking-wide text-[#0E7C72]">
            {index + 1} of {steps.length}
          </span>
          <button
            type="button"
            onClick={() => void finish()}
            aria-label="Close the tour"
            className="-mr-2 ml-auto flex h-10 w-10 items-center justify-center rounded-lg text-[#4A5558] hover:bg-[#EEF3F2] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/40 focus-visible:outline-none"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <h2 id="tour-title" className="text-xl font-semibold tracking-tight">
          {step.title}
        </h2>
        <p id="tour-body" className="text-[15px] leading-relaxed text-[#4A5558]">
          {step.body}
        </p>

        <div className="flex gap-1.5 pt-1" aria-hidden="true">
          {steps.map((s, i) => (
            <span key={s.title} className={cn('h-1.5 flex-1 rounded-full', i <= index ? 'bg-[#2EC4B6]' : 'bg-[#E3E9E8]')} />
          ))}
        </div>

        <div className="mt-1 flex items-center gap-2">
          {index === 0 ? (
            <button
              type="button"
              onClick={() => void finish()}
              className="h-11 rounded-xl px-3 text-[15px] font-medium text-[#4A5558] hover:bg-[#EEF3F2] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/40 focus-visible:outline-none"
            >
              Skip tour
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setIndex((i) => i - 1)}
              className="h-11 rounded-xl px-3 text-[15px] font-medium text-[#4A5558] hover:bg-[#EEF3F2] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/40 focus-visible:outline-none"
            >
              Back
            </button>
          )}
          <button
            type="button"
            data-testid="tour-next"
            onClick={() => (last ? void finish() : setIndex((i) => i + 1))}
            className="ml-auto h-11 rounded-xl bg-[#2EC4B6] px-5 text-[15px] font-semibold text-[#062320] hover:bg-[#27B0A3] focus-visible:ring-3 focus-visible:ring-[#0E7C72]/50 focus-visible:outline-none"
          >
            {index === 0 ? 'Show me around' : last ? 'Done' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  )
}
