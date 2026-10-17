import { apiRequest } from '@/lib/api-client'
import type { PatientCarePlanResponse } from '@/types/patient-access'
import type { MyProfile, MyVisitsResponse, PatientSession } from '@/types/patient-app'

// The patient's own API. Each call carries the patient session (asPatient),
// never a staff token.

export function requestSignInLink(email: string): Promise<{ detail: string }> {
  return apiRequest('/patient-app/request-link', { method: 'POST', body: { email }, skipAuth: true })
}

export function exchangeSignInLink(token: string): Promise<PatientSession> {
  return apiRequest<PatientSession>('/patient-app/exchange', { method: 'POST', body: { token }, skipAuth: true })
}

export function getMyProfile(): Promise<MyProfile> {
  return apiRequest<MyProfile>('/patient-app/me', { asPatient: true })
}

export function getMyCarePlan(): Promise<PatientCarePlanResponse> {
  return apiRequest<PatientCarePlanResponse>('/patient-app/me/care-plan', { asPatient: true })
}

export function getMyVisits(): Promise<MyVisitsResponse> {
  return apiRequest<MyVisitsResponse>('/patient-app/me/visits', { asPatient: true })
}
