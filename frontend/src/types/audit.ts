export type ActorType = 'CLINICIAN' | 'PATIENT' | 'SYSTEM'

export interface AuditEvent {
  id: string
  event_type: string
  actor_type: ActorType
  actor_id: string | null
  patient_id: string | null
  entity_type: string | null
  entity_id: string | null
  event_metadata: Record<string, unknown>
  created_at: string
}

export interface AuditEventListResponse {
  total: number
  results: AuditEvent[]
}
