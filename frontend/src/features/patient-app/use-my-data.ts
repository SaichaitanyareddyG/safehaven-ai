import { useQuery } from '@tanstack/react-query'

import { useEffect } from 'react'

import { getMyCarePlan, getMyDoses, getMyProfile, getMyVisits } from '@/api/patient-app'
import { getPatientToken } from '@/lib/auth-storage'
import type { PatientCareInstructionView } from '@/types/patient-access'
import type { Language } from '@/types/patients'

// Every key starts with 'my' so signing out can drop them all at once.
export function useMyProfile() {
  return useQuery({ queryKey: ['my', 'profile'], queryFn: getMyProfile, enabled: !!getPatientToken() })
}

export function useMyCarePlan() {
  return useQuery({ queryKey: ['my', 'care-plan'], queryFn: getMyCarePlan, enabled: !!getPatientToken() })
}

export function useMyDoses() {
  return useQuery({ queryKey: ['my', 'doses'], queryFn: getMyDoses, enabled: !!getPatientToken() })
}

export function useMyVisits() {
  return useQuery({ queryKey: ['my', 'visits'], queryFn: getMyVisits, enabled: !!getPatientToken() })
}

/** The patient's language when a checked translation exists, else English. */
export function textFor(instruction: PatientCareInstructionView, language: Language): string {
  return instruction.text_by_language[language] ?? instruction.text_by_language.ENGLISH ?? ''
}

/** Today in the phone's calendar, "YYYY-MM-DD" (comparable with API dates). */
export function todayIso(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

export function courseEnded(instruction: PatientCareInstructionView, today = todayIso()): boolean {
  const end = instruction.schedule?.end_date
  return !!end && end < today
}

/** Makes the patient pages installable as their own Home Screen app ("SafeHaven",
 *  opening at /my) — added only here, so the staff dashboard is never offered
 *  as the patient app. iPhone needs the app on the Home Screen for reminders. */
export function usePatientAppHead() {
  useEffect(() => {
    const added: HTMLElement[] = []
    const add = (tag: 'link' | 'meta', attrs: Record<string, string>) => {
      const el = document.createElement(tag)
      for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v)
      document.head.appendChild(el)
      added.push(el)
    }
    add('link', { rel: 'manifest', href: '/app/manifest.webmanifest' })
    add('link', { rel: 'apple-touch-icon', href: '/app/apple-touch-icon.png' })
    add('meta', { name: 'mobile-web-app-capable', content: 'yes' })
    add('meta', { name: 'apple-mobile-web-app-capable', content: 'yes' })
    add('meta', { name: 'apple-mobile-web-app-title', content: 'SafeHaven' })
    add('meta', { name: 'theme-color', content: '#143440' })
    return () => added.forEach((el) => el.remove())
  }, [])
}
