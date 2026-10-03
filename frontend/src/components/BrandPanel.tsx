import { Bell, MessageSquare, Pill } from 'lucide-react'
import type { ReactNode } from 'react'

/**
 * The dark teal brand side of the sign-in screens (sign in, choose a
 * password): the band's beacon rings, the headline and what SafeHaven does.
 * On a phone it shrinks to a header the card overlaps.
 */
export function BrandPanel() {
  return (
    <section className="relative flex flex-col gap-5 overflow-hidden bg-[#0A2422] px-6 pt-7 pb-16 text-[#F2F4F3] lg:min-h-screen lg:flex-1 lg:gap-10 lg:px-16 lg:py-14">
      <BeaconRings />
      <div className="relative flex items-center gap-3">
        <Logo className="h-7 w-7 lg:h-[34px] lg:w-[34px]" />
        <span className="text-base font-semibold tracking-[0.25em] text-[#7FE0D6] lg:text-xl">SAFEHAVEN AI</span>
      </div>
      <div className="relative flex max-w-xl flex-col gap-5 lg:mt-auto">
        <h1 className="text-3xl leading-tight font-semibold tracking-tight lg:text-[52px] lg:leading-[1.08]">
          Calm, watchful care for every bed.
        </h1>
        <p className="hidden text-lg leading-relaxed text-[#B8C3C1] lg:block">
          Fall alerts from the wrist band, medication checks at the bedside, and care plans patients understand — in
          one place for the ward.
        </p>
      </div>
      <ul className="relative hidden max-w-xl flex-col gap-3.5 lg:flex">
        <Feature icon={<Bell className="h-5 w-5" />} text="Fall and help alerts in seconds" />
        <Feature icon={<Pill className="h-5 w-5" />} text="Right medicine, right patient, every time" />
        <Feature icon={<MessageSquare className="h-5 w-5" />} text="Care plans explained in the patient's words" />
      </ul>
    </section>
  )
}

function Feature({ icon, text }: { icon: ReactNode; text: string }) {
  return (
    <li className="flex items-center gap-3.5 text-base text-[#DCE4E2]">
      <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-[#0F3B37] text-[#7FE0D6]" aria-hidden="true">
        {icon}
      </span>
      {text}
    </li>
  )
}

/** The SafeHaven mark: a pulse line inside a ring. */
export function Logo({ className }: { className?: string }) {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true" className={className}>
      <circle cx="17" cy="17" r="15" fill="none" stroke="#2EC4B6" strokeWidth="2.5" />
      <path
        d="M7 18 L12 18 L14.5 12 L18.5 23 L21 16 L27 16"
        fill="none"
        stroke="#2EC4B6"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** The band's fall-alert "beacon", as quiet concentric rings. */
function BeaconRings() {
  return (
    <svg
      viewBox="0 0 760 760"
      aria-hidden="true"
      className="pointer-events-none absolute -top-40 -right-44 h-[420px] w-[420px] lg:top-auto lg:-right-64 lg:-bottom-64 lg:h-[760px] lg:w-[760px]"
    >
      <circle cx="380" cy="380" r="120" fill="none" stroke="#2EC4B6" strokeOpacity="0.35" strokeWidth="2" />
      <circle cx="380" cy="380" r="200" fill="none" stroke="#2EC4B6" strokeOpacity="0.22" strokeWidth="2" />
      <circle cx="380" cy="380" r="280" fill="none" stroke="#2EC4B6" strokeOpacity="0.14" strokeWidth="2" />
      <circle cx="380" cy="380" r="360" fill="none" stroke="#2EC4B6" strokeOpacity="0.08" strokeWidth="2" />
      <circle cx="380" cy="380" r="60" fill="#2EC4B6" fillOpacity="0.18" />
    </svg>
  )
}
