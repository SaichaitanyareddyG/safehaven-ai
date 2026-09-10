import { ApiError, apiRequest } from '@/lib/api-client'
import { clearToken, getToken } from '@/lib/auth-storage'
import type { ConfirmedProductCandidate, ImageIdentificationResponse, VerifyResponse } from '@/types/medication-verification'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

export function verifyMedication(patientCode: string, barcode: string): Promise<VerifyResponse> {
  return apiRequest<VerifyResponse>('/medication-verification/verify', {
    method: 'POST',
    body: { patient_code: patientCode, barcode },
  })
}

export function administerMedication(verificationId: string): Promise<{ id: string; administered_at: string }> {
  return apiRequest('/medication-verification/administer', {
    method: 'POST',
    body: { verification_id: verificationId },
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
