import type { InstructionType } from '@/types/instructions'
import type { Language } from '@/types/patients'

export interface CareAccessTokenCreateResponse {
  token: string
  expires_at: string
}

export type CareAccessTokenStatus = 'ACTIVE' | 'EXPIRED' | 'REVOKED'

export interface CareAccessTokenSummary {
  id: string
  created_at: string
  expires_at: string
  revoked_at: string | null
  status: CareAccessTokenStatus
}

export interface CareAccessTokenListResponse {
  total: number
  results: CareAccessTokenSummary[]
}

export type WhyTier = 'DOCUMENTED' | 'GENERAL' | 'NONE'

export interface WhyExplanation {
  tier: WhyTier
  text: string
  disclaimer: string | null
}

export interface PatientCareInstructionView {
  id: string
  instruction_type: InstructionType | null
  text_by_language: Partial<Record<Language, string>>
  approved_at: string
  why: WhyExplanation | null
}

export interface PatientCarePlanResponse {
  patient_first_name: string
  preferred_language: Language
  instructions: PatientCareInstructionView[]
  // Medications whose clinical status is COMPLETED or STOPPED — shown
  // separately, never simply omitted.
  past_medications: PatientCareInstructionView[]
}
