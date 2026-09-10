import type { Language } from '@/types/patients'

export type InstructionStatus =
  | 'DRAFT'
  | 'PROCESSING'
  | 'NEEDS_REVIEW'
  | 'READY_FOR_APPROVAL'
  | 'APPROVED'
  | 'REJECTED'

export type VersionSource = 'ORIGINAL' | 'CLARIFICATION'

export type InstructionType = 'MEDICATION' | 'MOBILITY' | 'DIET' | 'WOUND_CARE' | 'FOLLOW_UP' | 'GENERAL'

export type CompletenessStatus = 'PASSED' | 'NEEDS_CLARIFICATION' | 'FAILED'

export type ValidationStatus = 'PENDING' | 'PASSED' | 'FAILED'

export type FactDifferenceType = 'CHANGED' | 'MISSING' | 'ADDED' | 'AMBIGUOUS'

// Medication-only (see backend ClinicalStatus docstring) — always null for
// mobility/diet/wound-care/follow-up/general instructions.
export type ClinicalStatus = 'ACTIVE' | 'COMPLETED' | 'STOPPED'

export interface EncounterSummary {
  id: string
  reason_for_visit: string | null
  admission_date: string
}

export interface FactDifference {
  field: string
  source: unknown
  generated: unknown
  type: FactDifferenceType
}

export interface StructuredExtractionRead {
  id: string
  instruction_type: InstructionType | null
  extracted_facts: Record<string, unknown>
  normalized_facts: Record<string, unknown>
  missing_fields: string[]
  ambiguous_fields: string[]
  clarification_required_fields: string[]
  validation_messages: string[]
  completeness_status: CompletenessStatus
  provider: string
  model: string
  prompt_version: string
  created_at: string
}

export interface PatientOutputTranslationRead {
  id: string
  language: Language
  translated_text: string | null
  validation_status: ValidationStatus
  validation_diff: FactDifference[]
  validation_messages: string[]
  provider: string
  model: string
  prompt_version: string
  created_at: string
}

export interface PatientOutputRead {
  id: string
  attempt_number: number
  patient_text_en: string | null
  validation_status: ValidationStatus
  validation_diff: FactDifference[]
  validation_messages: string[]
  provider: string
  model: string
  prompt_version: string
  created_at: string
  translations: PatientOutputTranslationRead[]
}

export interface TranslationResultItem {
  status: ValidationStatus
}

export interface InstructionVersionRead {
  id: string
  version_number: number
  raw_text: string
  source: VersionSource
  created_at: string
  extraction: StructuredExtractionRead | null
  patient_outputs: PatientOutputRead[]
}

export interface CareInstructionRead {
  id: string
  patient_id: string
  status: InstructionStatus
  review_reason: string | null
  approved_at: string | null
  created_at: string
  updated_at: string
  current_version: InstructionVersionRead | null
  encounter: EncounterSummary | null
  clinical_status: ClinicalStatus | null
  clinical_start_date: string | null
  clinical_end_date: string | null
}

export interface CareInstructionDetail extends CareInstructionRead {
  versions: InstructionVersionRead[]
}

export interface CareInstructionListResponse {
  total: number
  results: CareInstructionRead[]
}
