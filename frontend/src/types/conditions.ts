export interface PatientCondition {
  id: string
  patient_id: string
  condition_name: string
  documented_by: string
  documented_at: string
}

export interface PatientConditionListResponse {
  total: number
  results: PatientCondition[]
}
