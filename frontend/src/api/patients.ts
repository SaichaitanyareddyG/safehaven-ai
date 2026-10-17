import { apiRequest } from '@/lib/api-client'
import type {
  AdmissionStatus,
  AppAccess,
  AppInviteResponse,
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
