export interface Appointment {
  id: string
  patient_id: string
  title: string
  starts_at: string
  location: string | null
  notes: string | null
  status: 'SCHEDULED' | 'CANCELLED'
  created_at: string
  updated_at: string
}
