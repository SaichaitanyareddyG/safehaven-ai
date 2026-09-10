import { apiRequest } from '@/lib/api-client'
import type { EncounterCreate, EncounterListResponse, EncounterRead } from '@/types/encounters'

export function listEncounters(patientId: string): Promise<EncounterListResponse> {
  return apiRequest<EncounterListResponse>(`/patients/${patientId}/encounters`)
}

export function createEncounter(patientId: string, data: EncounterCreate): Promise<EncounterRead> {
  return apiRequest<EncounterRead>(`/patients/${patientId}/encounters`, { method: 'POST', body: data })
}
