export type Language = 'ENGLISH' | 'TELUGU' | 'HINDI'

export type AdmissionStatus = 'ACTIVE' | 'DISCHARGED'

export interface Patient {
  id: string
  patient_code: string
  first_name: string
  last_name: string
  date_of_birth: string
  room_number: string | null
  preferred_language: Language
  admission_status: AdmissionStatus
  created_at: string
  updated_at: string
}

export interface PatientListResponse {
  total: number
  results: Patient[]
}

export interface PatientCreate {
  first_name: string
  last_name: string
  date_of_birth: string
  room_number?: string | null
  preferred_language: Language
}

export interface PatientUpdate {
  first_name?: string
  last_name?: string
  date_of_birth?: string
  room_number?: string | null
  preferred_language?: Language
  admission_status?: AdmissionStatus
}
