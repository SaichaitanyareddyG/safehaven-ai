import { apiRequest } from '@/lib/api-client'
import type { AdmissionStatus, Patient, PatientCreate, PatientListResponse, PatientUpdate } from '@/types/patients'

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

export function createPatient(payload: PatientCreate): Promise<Patient> {
  return apiRequest<Patient>('/patients', { method: 'POST', body: payload })
}

export function updatePatient(patientId: string, payload: PatientUpdate): Promise<Patient> {
  return apiRequest<Patient>(`/patients/${patientId}`, { method: 'PATCH', body: payload })
}
