export type Language =
  | 'ENGLISH'
  | 'TELUGU'
  | 'HINDI'
  | 'SPANISH'
  | 'MANDARIN'
  | 'VIETNAMESE'
  | 'TAGALOG'
  | 'ARABIC'
  | 'KOREAN'
  | 'RUSSIAN'
  | 'FRENCH'

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
  email: string | null
  phone: string | null
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
  reason_for_visit?: string | null
  /** With app_consent, registering also emails the patient-app invite. */
  email?: string | null
  phone?: string | null
  app_consent?: boolean
}

export interface AppInviteOutcome {
  emailed: boolean
  problem: string | null
  /** Only when the email did not go, for staff to pass on another way. */
  link: string | null
}

export interface PatientCreateResponse extends Patient {
  app_invite: AppInviteOutcome | null
}

export type AppAccessStatus = 'NOT_INVITED' | 'INVITED' | 'ACTIVE' | 'REVOKED' | 'EXPIRED'

export interface Caregiver {
  id: string
  display_name: string | null
  relationship: string | null
  email: string | null
  status: AppAccessStatus
  invited_at: string | null
  last_sign_in_at: string | null
}

export interface AppAccess {
  /** Family members or carers with their own login to this patient's app. */
  caregivers: Caregiver[]
  status: AppAccessStatus
  email: string | null
  phone: string | null
  consent_at: string | null
  invited_at: string | null
  activated_at: string | null
  last_sign_in_at: string | null
  access_expires_at: string | null
}

export interface AppInviteResponse extends AppInviteOutcome {
  access: AppAccess
}

export interface PatientUpdate {
  first_name?: string
  last_name?: string
  date_of_birth?: string
  room_number?: string | null
  preferred_language?: Language
  admission_status?: AdmissionStatus
  email?: string | null
  phone?: string | null
}

export interface MissedDosesFlag {
  patient_id: string
  date: string
  missed: number
  skipped: number
}
