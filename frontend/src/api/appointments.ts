import { apiRequest } from '@/lib/api-client'
import type { Appointment } from '@/types/appointments'

export function listAppointments(patientId: string): Promise<{ results: Appointment[] }> {
  return apiRequest<{ results: Appointment[] }>(`/patients/${patientId}/appointments`)
}

export function createAppointment(
  patientId: string,
  payload: { title: string; starts_at: string; location?: string | null; notes?: string | null },
): Promise<Appointment> {
  return apiRequest<Appointment>(`/patients/${patientId}/appointments`, { method: 'POST', body: payload })
}

export function updateAppointment(
  appointmentId: string,
  payload: Partial<Pick<Appointment, 'title' | 'starts_at' | 'location' | 'notes' | 'status'>>,
): Promise<Appointment> {
  return apiRequest<Appointment>(`/appointments/${appointmentId}`, { method: 'PATCH', body: payload })
}
