export interface PatientAllergy {
  id: string
  patient_id: string
  allergen: string
  reaction: string | null
  severity: string | null
  documented_by: string
  documented_at: string
}

export interface PatientAllergyListResponse {
  total: number
  results: PatientAllergy[]
}
