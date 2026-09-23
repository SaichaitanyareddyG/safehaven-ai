import { apiRequest } from '@/lib/api-client'
import type {
  AlertStatus,
  DeviceAssignment,
  MonitoringProfile,
  PatientAssignmentResponse,
  SafetyAlert,
  SafetyAlertListResponse,
  SensorEventListResponse,
  WearableDeviceListResponse,
} from '@/types/safety-monitoring'

/**
 * The cross-patient alert queue.
 *
 * Defaults to live alerts (OPEN + ACKNOWLEDGED) server-side. Pass `status` only
 * when deliberately looking at history — a queue showing resolved alerts by
 * default would bury the ones needing action.
 */
export function listSafetyAlerts(status?: AlertStatus[]): Promise<SafetyAlertListResponse> {
  const query = status?.length ? `?${status.map((s) => `status=${s}`).join('&')}` : ''
  return apiRequest<SafetyAlertListResponse>(`/safety-alerts${query}`)
}

export function acknowledgeSafetyAlert(alertId: string): Promise<SafetyAlert> {
  return apiRequest<SafetyAlert>(`/safety-alerts/${alertId}/acknowledge`, { method: 'POST' })
}

export function resolveSafetyAlert(alertId: string): Promise<SafetyAlert> {
  return apiRequest<SafetyAlert>(`/safety-alerts/${alertId}/resolve`, { method: 'POST' })
}

// ── devices and assignment (staff) ──────────────────────────────────────────

export function listWearableDevices(): Promise<WearableDeviceListResponse> {
  return apiRequest<WearableDeviceListResponse>('/wearable-devices')
}

export function getPatientAssignment(patientId: string): Promise<PatientAssignmentResponse> {
  return apiRequest<PatientAssignmentResponse>(`/patients/${patientId}/wearable-assignment`)
}

export function assignWearable(
  patientId: string,
  deviceId: string,
  monitoringProfile: MonitoringProfile,
): Promise<DeviceAssignment> {
  return apiRequest<DeviceAssignment>(`/patients/${patientId}/wearable-assignment`, {
    method: 'POST',
    body: { device_id: deviceId, monitoring_profile: monitoringProfile },
  })
}

export function unassignWearable(patientId: string): Promise<DeviceAssignment> {
  return apiRequest<DeviceAssignment>(`/patients/${patientId}/wearable-assignment`, {
    method: 'DELETE',
  })
}

export function listPatientSafetyEvents(patientId: string): Promise<SensorEventListResponse> {
  return apiRequest<SensorEventListResponse>(`/patients/${patientId}/safety-events`)
}
