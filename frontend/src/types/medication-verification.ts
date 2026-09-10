export type VerificationResult = 'VERIFIED' | 'WARNING' | 'BLOCKED' | 'REVIEW_REQUIRED'
export type IdentificationMethod = 'BARCODE' | 'IMAGE'

export interface CheckResult {
  passed: boolean
  detail: string
}

export interface MedicationProduct {
  barcode: string
  medication_name: string
  strength_value: number
  strength_unit: string
  formulation: string
  route: string
}

export interface VerifyResponse {
  id: string
  result: VerificationResult
  identification_method: IdentificationMethod
  checks: Record<string, CheckResult>
  mismatch_reasons: string[]
  care_instruction_id: string | null
  product: MedicationProduct | null
  created_at: string
}

// --- Image fallback (barcode failure) ---

export interface ImageIdentificationResponse {
  medication_name: string | null
  strength_value: number | null
  strength_unit: string | null
  formulation: string | null
  route: string | null
  confidence: 'high' | 'low'
}

export interface ConfirmedProductCandidate {
  medication_name: string
  strength_value: number
  strength_unit: string
  formulation: string
  route: string
}
