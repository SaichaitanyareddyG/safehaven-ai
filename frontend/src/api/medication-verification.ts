import { ApiError, apiRequest } from '@/lib/api-client'
import { clearToken, getToken } from '@/lib/auth-storage'
import type {
  AdministrationHistoryResponse,
  ConfirmedProductCandidate,
  ImageIdentificationResponse,
  NotGivenReason,
  VerifyResponse,
} from '@/types/medication-verification'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

export function verifyMedication(patientCode: string, barcode: string): Promise<VerifyResponse> {
  return apiRequest<VerifyResponse>('/medication-verification/verify', {
    method: 'POST',
    body: { patient_code: patientCode, barcode },
  })
}

export function administerMedication(
  verificationId: string,
  coSigner?: { email: string; password: string },
  administrationReason?: string,
): Promise<{ id: string; administered_at: string }> {
  return apiRequest('/medication-verification/administer', {
    method: 'POST',
    body: {
      verification_id: verificationId,
      co_signer_email: coSigner?.email,
      co_signer_password: coSigner?.password,
      administration_reason: administrationReason,
    },
  })
}

// Multipart upload — apiRequest only handles JSON bodies, so this makes its
// own fetch call, matching the same auth-header/401 handling.
export async function identifyMedicationFromImage(
  file: File,
  patientId?: string,
): Promise<ImageIdentificationResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (patientId) formData.append('patient_id', patientId)

  const token = getToken()
  const response = await fetch(new URL('/medication-verification/identify-from-image', API_BASE_URL), {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })

  if (response.status === 401) {
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText)
  }
  return response.json()
}

export function verifyConfirmedMedication(
  patientCode: string,
  candidate: ConfirmedProductCandidate,
): Promise<VerifyResponse> {
  return apiRequest<VerifyResponse>('/medication-verification/verify-confirmed', {
    method: 'POST',
    body: { patient_code: patientCode, candidate },
  })
}

export function recordNotGiven(
  verificationId: string,
  reason: NotGivenReason,
  note?: string,
): Promise<{ id: string; not_given_at: string }> {
  return apiRequest('/medication-verification/not-given', {
    method: 'POST',
    body: { verification_id: verificationId, reason, note },
  })
}

export function listAdministrationHistory(patientId: string): Promise<AdministrationHistoryResponse> {
  return apiRequest<AdministrationHistoryResponse>(`/patients/${patientId}/administrations`)
}
