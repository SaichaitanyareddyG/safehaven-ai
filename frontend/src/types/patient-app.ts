import type { AdmissionStatus, Language } from '@/types/patients'

export interface PatientSession {
  access_token: string
  token_type: string
  expires_at: string
}

export interface MyProfile {
  first_name: string
  last_name: string
  preferred_language: Language
  admission_status: AdmissionStatus
  room_number: string | null
  /** Set after discharge: the app stops working after this. */
  access_expires_at: string | null
}

export interface MyVisit {
  id: string
  reason_for_visit: string | null
  encounter_type: string | null
  planned_procedure: string | null
  nil_by_mouth_from: string | null
  admission_date: string
  discharge_date: string | null
  status: 'OPEN' | 'CLOSED'
}

export interface MyVisitsResponse {
  visits: MyVisit[]
}
