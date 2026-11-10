import { apiRequest } from '@/lib/api-client'
import type {
  AdmissionStatus,
  AppAccess,
  AppInviteResponse,
  CarePlanPrintout,
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

/** Paused: no sign-in, no reminders; the password is kept for reactivating. */
export function deactivateAppAccess(patientId: string): Promise<AppAccess> {
  return apiRequest<AppAccess>(`/patients/${patientId}/app-access/deactivate`, { method: 'POST' })
}

export function reactivateAppAccess(patientId: string): Promise<AppAccess> {
  return apiRequest<AppAccess>(`/patients/${patientId}/app-access/reactivate`, { method: 'POST' })
}

/** Removes the patient's app login for good; the record and history stay. */
export function deleteAppAccess(patientId: string): Promise<void> {
  return apiRequest<void>(`/patients/${patientId}/app-access`, { method: 'DELETE' })
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

export function deactivateCaregiver(patientId: string, caregiverId: string): Promise<Caregiver> {
  return apiRequest<Caregiver>(`/patients/${patientId}/app-access/caregivers/${caregiverId}/deactivate`, { method: 'POST' })
}

export function reactivateCaregiver(patientId: string, caregiverId: string): Promise<Caregiver> {
  return apiRequest<Caregiver>(`/patients/${patientId}/app-access/caregivers/${caregiverId}/reactivate`, { method: 'POST' })
}

export function deleteCaregiver(patientId: string, caregiverId: string): Promise<void> {
  return apiRequest<void>(`/patients/${patientId}/app-access/caregivers/${caregiverId}`, { method: 'DELETE' })
}

export function getCarePlanPrintout(patientId: string): Promise<CarePlanPrintout> {
  return apiRequest<CarePlanPrintout>(`/patients/${patientId}/care-plan-printout`)
}
