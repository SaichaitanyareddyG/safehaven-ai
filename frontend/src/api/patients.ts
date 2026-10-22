import { apiRequest } from '@/lib/api-client'
import type {
  AdmissionStatus,
  AppAccess,
  AppInviteResponse,
  Caregiver,
  MissedDosesFlag,
  Patient,
  PatientCreate,
  PatientCreateResponse,
  PatientListResponse,
  PatientUpdate,
} from '@/types/patients'

export interface ListPatientsParams {
  status?: AdmissionStatus
  search?: string
  limit?: number
  offset?: number
}

export function listPatients(params: ListPatientsParams = {}): Promise<PatientListResponse> {
  return apiRequest<PatientListResponse>('/patients', { params })
}

export function getPatient(patientId: string): Promise<Patient> {
  return apiRequest<Patient>(`/patients/${patientId}`)
}

// Exact-match wristband scan lookup — see api/medication-verification.ts.
export function getPatientByCode(patientCode: string): Promise<Patient> {
  return apiRequest<Patient>(`/patients/by-code/${encodeURIComponent(patientCode)}`)
}

export function createPatient(payload: PatientCreate): Promise<PatientCreateResponse> {
  return apiRequest<PatientCreateResponse>('/patients', { method: 'POST', body: payload })
}

export function updatePatient(patientId: string, payload: PatientUpdate): Promise<Patient> {
  return apiRequest<Patient>(`/patients/${patientId}`, { method: 'PATCH', body: payload })
}

// Patient app access (staff side) — see features/patients/PatientAppPanel.tsx.
export function getAppAccess(patientId: string): Promise<AppAccess> {
  return apiRequest<AppAccess>(`/patients/${patientId}/app-access`)
}

export function inviteToApp(
  patientId: string,
  payload: { email?: string | null; phone?: string | null; consent?: boolean } = {},
): Promise<AppInviteResponse> {
  return apiRequest<AppInviteResponse>(`/patients/${patientId}/app-access/invite`, { method: 'POST', body: payload })
}

export function revokeAppAccess(patientId: string): Promise<AppAccess> {
  return apiRequest<AppAccess>(`/patients/${patientId}/app-access/revoke`, { method: 'POST' })
}

/** Patients at home who missed 2+ doses in the app today or yesterday. */
export function getMissedDoses(): Promise<{ flags: MissedDosesFlag[] }> {
  return apiRequest<{ flags: MissedDosesFlag[] }>('/patients/missed-doses')
}

export function inviteCaregiver(
  patientId: string,
  payload: { email: string; name: string; relationship?: string | null; consent: boolean },
): Promise<{ caregiver: Caregiver; emailed: boolean; problem: string | null; link: string | null }> {
  return apiRequest(`/patients/${patientId}/app-access/caregivers`, { method: 'POST', body: payload })
}

export function revokeCaregiver(patientId: string, caregiverId: string): Promise<Caregiver> {
  return apiRequest<Caregiver>(`/patients/${patientId}/app-access/caregivers/${caregiverId}/revoke`, { method: 'POST' })
}
