import { ApiError, apiRequest } from '@/lib/api-client'
import { getPatientToken } from '@/lib/auth-storage'
import type { Appointment } from '@/types/appointments'
import type { PatientCarePlanResponse } from '@/types/patient-access'
import type { ChatMessageListResponse, ChatSendResponse } from '@/types/patient-chat'
import type {
  AdherenceResponse,
  MyDosesResponse,
  MyProfile,
  MyVisitsResponse,
  PatientSession,
  PushStatus,
} from '@/types/patient-app'

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

export function getMyDoses(): Promise<MyDosesResponse> {
  return apiRequest<MyDosesResponse>('/patient-app/me/doses', { asPatient: true })
}

/** status null = undo. */
export function recordDose(payload: {
  instruction_id: string
  date: string
  time: string
  status: 'TAKEN' | 'SKIPPED' | null
}): Promise<void> {
  return apiRequest<void>('/patient-app/me/doses', { method: 'POST', body: payload, asPatient: true })
}

export function getPushStatus(): Promise<PushStatus> {
  return apiRequest<PushStatus>('/patient-app/push', { skipAuth: true })
}

export function savePushSubscription(subscription: PushSubscriptionJSON): Promise<void> {
  return apiRequest<void>('/patient-app/me/push', { method: 'POST', body: subscription, asPatient: true })
}

export function removePushSubscription(endpoint: string): Promise<void> {
  return apiRequest<void>('/patient-app/me/push/remove', { method: 'POST', body: { endpoint }, asPatient: true })
}

// Staff side.
export function getAdherence(patientId: string, days = 14): Promise<AdherenceResponse> {
  return apiRequest<AdherenceResponse>(`/patients/${patientId}/app-access/adherence`, { params: { days } })
}

export function getMyChat(): Promise<ChatMessageListResponse> {
  return apiRequest<ChatMessageListResponse>('/patient-app/me/chat', { asPatient: true })
}

export function sendMyChat(text: string): Promise<ChatSendResponse> {
  return apiRequest<ChatSendResponse>('/patient-app/me/chat', { method: 'POST', body: { text }, asPatient: true })
}

/** Speech for text the app is already showing (an audio body, not JSON). */
export async function getMyAudio(text: string): Promise<Blob> {
  const response = await fetch(new URL('/patient-app/me/audio', import.meta.env.VITE_API_BASE_URL), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getPatientToken() ?? ''}` },
    body: JSON.stringify({ text }),
  })
  if (!response.ok) throw new ApiError(response.status, 'Speech is not available right now')
  return response.blob()
}

export function getMyAppointments(): Promise<{ results: Appointment[] }> {
  return apiRequest<{ results: Appointment[] }>('/patient-app/me/appointments', { asPatient: true })
}
