import { apiRequest } from '@/lib/api-client'
import type { AuditEventListResponse } from '@/types/audit'

export function listPatientAuditEvents(patientId: string): Promise<AuditEventListResponse> {
  return apiRequest<AuditEventListResponse>(`/patients/${patientId}/audit`, { params: { limit: 200 } })
}
