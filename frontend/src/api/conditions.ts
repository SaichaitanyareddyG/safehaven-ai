import { apiRequest } from '@/lib/api-client'
import type { PatientCondition, PatientConditionListResponse } from '@/types/conditions'

export function listConditions(patientId: string): Promise<PatientConditionListResponse> {
  return apiRequest<PatientConditionListResponse>(`/patients/${patientId}/conditions`)
}

export function createCondition(patientId: string, conditionName: string): Promise<PatientCondition> {
  return apiRequest<PatientCondition>(`/patients/${patientId}/conditions`, {
    method: 'POST',
    body: { condition_name: conditionName },
  })
}

export function deleteCondition(patientId: string, conditionId: string): Promise<void> {
  return apiRequest<void>(`/patients/${patientId}/conditions/${conditionId}`, { method: 'DELETE' })
}
