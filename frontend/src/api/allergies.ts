import { apiRequest } from '@/lib/api-client'
import type { PatientAllergy, PatientAllergyListResponse } from '@/types/allergies'

export function listAllergies(patientId: string): Promise<PatientAllergyListResponse> {
  return apiRequest<PatientAllergyListResponse>(`/patients/${patientId}/allergies`)
}

export function createAllergy(patientId: string, allergen: string): Promise<PatientAllergy> {
  return apiRequest<PatientAllergy>(`/patients/${patientId}/allergies`, {
    method: 'POST',
    body: { allergen },
  })
}

export function deleteAllergy(patientId: string, allergyId: string): Promise<void> {
  return apiRequest<void>(`/patients/${patientId}/allergies/${allergyId}`, { method: 'DELETE' })
}
