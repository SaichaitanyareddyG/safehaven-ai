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
  // ISMP High-Alert Medications — see app/reference/medication_products.py.
  // Gates the independent second-clinician co-sign requirement below.
  high_alert: boolean
}

export interface VerifyResponse {
  id: string
  result: VerificationResult
  identification_method: IdentificationMethod
  checks: Record<string, CheckResult>
  mismatch_reasons: string[]
  care_instruction_id: string | null
  product: MedicationProduct | null
  // True when the matched order is as-needed (PRN) — an indication must then
  // be recorded before administration can be confirmed.
  order_is_prn: boolean
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

export type NotGivenReason = 'REFUSED' | 'HELD' | 'PATIENT_UNAVAILABLE' | 'VOMITED' | 'OTHER'

export interface AdministrationHistoryItem {
  id: string
  created_at: string
  verification_result: VerificationResult
  identification_method: IdentificationMethod
  mismatch_reasons: string[]
  identified_medication_name: string | null
  identified_strength_value: number | null
  identified_strength_unit: string | null
  administered_at: string | null
  administered_by: string | null
  co_signed_by: string | null
  administration_reason: string | null
  not_given_reason: NotGivenReason | null
  not_given_note: string | null
  not_given_at: string | null
}

export interface AdministrationHistoryResponse {
  total: number
  results: AdministrationHistoryItem[]
}
