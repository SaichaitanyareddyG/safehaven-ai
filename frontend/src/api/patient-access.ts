import { apiRequest } from '@/lib/api-client'
import type {
  CareAccessTokenCreateResponse,
  CareAccessTokenListResponse,
  CareAccessTokenSummary,
  PatientCarePlanResponse,
} from '@/types/patient-access'

export function createCareAccessToken(
  patientId: string,
  expiresInHours?: number,
): Promise<CareAccessTokenCreateResponse> {
  return apiRequest<CareAccessTokenCreateResponse>(`/patients/${patientId}/care-access-tokens`, {
    method: 'POST',
    body: { expires_in_hours: expiresInHours ?? null },
  })
}

export function listCareAccessTokens(patientId: string): Promise<CareAccessTokenListResponse> {
  return apiRequest<CareAccessTokenListResponse>(`/patients/${patientId}/care-access-tokens`)
}

export function revokeCareAccessToken(tokenId: string): Promise<CareAccessTokenSummary> {
  return apiRequest<CareAccessTokenSummary>(`/care-access-tokens/${tokenId}/revoke`, { method: 'POST' })
}

// Public — no clinician session exists on this route, so skipAuth avoids
// attaching a stale/irrelevant Authorization header and avoids the 401
// interceptor redirecting a patient to the clinician login page.
export function getCarePlan(token: string): Promise<PatientCarePlanResponse> {
  return apiRequest<PatientCarePlanResponse>('/care-plan', { params: { token }, skipAuth: true })
}

// Returns a raw audio blob, not JSON — apiRequest always parses JSON, so this
// bypasses it with a plain fetch. Same public, token-gated endpoint pattern
// as getCarePlan above.
export async function getCarePlanAudio(token: string, text: string, language: string): Promise<Blob> {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL
  const response = await fetch(new URL('/care-plan/audio', apiBaseUrl), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, text, language }),
  })
  if (!response.ok) {
    throw new Error(`Speech synthesis failed (${response.status})`)
  }
  return response.blob()
}
