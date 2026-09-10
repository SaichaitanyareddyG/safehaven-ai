export type EncounterStatus = 'OPEN' | 'CLOSED'

export interface EncounterRead {
  id: string
  encounter_type: string | null
  reason_for_visit: string | null
  admission_date: string
  discharge_date: string | null
  status: EncounterStatus
  created_at: string
}

export interface EncounterCreate {
  encounter_type?: string | null
  reason_for_visit?: string | null
  admission_date: string
  discharge_date?: string | null
  status?: EncounterStatus
}

export interface EncounterListResponse {
  total: number
  results: EncounterRead[]
}
