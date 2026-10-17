import { useQuery } from '@tanstack/react-query'

import { getMyCarePlan, getMyProfile, getMyVisits } from '@/api/patient-app'
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

export interface DoseToday {
  time: string
  timeDisplay: string
  medicine: PatientCareInstructionView
}

/** Every scheduled dose due today, earliest first. As-needed medicines,
 *  ones without clear times, and courses not started or already ended are
 *  left out — never guessed. */
export function dosesToday(medicines: PatientCareInstructionView[], today = todayIso()): DoseToday[] {
  const doses: DoseToday[] = []
  for (const medicine of medicines) {
    const schedule = medicine.schedule
    if (!schedule || schedule.kind !== 'SCHEDULED') continue
    if (schedule.start_date && schedule.start_date > today) continue
    if (courseEnded(medicine, today)) continue
    schedule.times.forEach((time, i) => doses.push({ time, timeDisplay: schedule.times_display[i], medicine }))
  }
  return doses.sort((a, b) => a.time.localeCompare(b.time))
}
