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
