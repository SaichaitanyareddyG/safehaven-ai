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
  past_reason: 'STOPPED' | 'COMPLETED' | null
}

export interface ConditionExplainerView {
  what_it_is: string
  how_it_develops: string
  where_it_affects: string
}

export interface PatientConditionView {
  condition_name: string
  // Only set when the condition name matches the curated reference table
  // exactly — never a guess. A condition with no explainer still appears
  // (by name only) rather than being hidden.
  explainer: ConditionExplainerView | null
}

export interface PatientAllergyView {
  allergen: string
  reaction: string | null
  severity: string | null
}

export interface PatientCarePlanResponse {
  patient_first_name: string
  preferred_language: Language
  instructions: PatientCareInstructionView[]
  // Medications whose clinical status is COMPLETED or STOPPED — shown
  // separately, never simply omitted.
  past_medications: PatientCareInstructionView[]
  conditions: PatientConditionView[]
  allergies: PatientAllergyView[]
}
