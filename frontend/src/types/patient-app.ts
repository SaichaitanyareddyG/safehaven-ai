import type { AdmissionStatus, Language } from '@/types/patients'

export interface PatientSession {
  access_token: string
  token_type: string
  expires_at: string
}

export interface MyProfile {
  /** Whose login: the patient's own, or a caregiver viewing their care. */
  viewer_role: 'PATIENT' | 'CAREGIVER'
  viewer_name: string | null
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

export interface MyDose {
  instruction_id: string
  medication_name: string
  dose: string | null
  with_food: boolean | null
  /** "08:00", hospital local time */
  time: string
  time_display: string
  status: 'TAKEN' | 'SKIPPED' | null
  recorded_at: string | null
}

export interface MyDosesResponse {
  date: string
  /** false while admitted: nurses give the doses */
  at_home: boolean
  doses: MyDose[]
}

export interface PushStatus {
  available: boolean
  public_key: string | null
}

export interface AdherenceDay {
  date: string
  due: number
  taken: number
  skipped: number
}

export interface AdherenceResponse {
  days: AdherenceDay[]
  total_due: number
  total_taken: number
  total_skipped: number
}
