/** Module 3 — wearable patient-safety monitoring. */

export type AlertType =
  | 'POSSIBLE_FALL'
  | 'ABNORMAL_MOVEMENT'
  | 'UNEXPECTED_MOBILITY'
  | 'DEVICE_LOW_BATTERY'
  | 'DEVICE_OFFLINE'

/**
 * Operational priority — how soon someone should look. Deliberately NOT a
 * clinical severity: nothing in Module 3 can judge medical acuity.
 */
export type AlertPriority = 'LOW' | 'MEDIUM' | 'HIGH'

export type AlertStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'

export type MonitoringProfile = 'STANDARD' | 'FALL_RISK' | 'RESTRICTED_MOBILITY'

export interface SafetyAlert {
  id: string
  alert_type: AlertType
  priority: AlertPriority
  status: AlertStatus
  /**
   * Rendered server-side from a single table so the observed-not-diagnosed
   * wording cannot drift between surfaces. Render this; do not compose alert
   * text in the UI.
   */
  message: string

  patient_id: string
  patient_code: string
  patient_name: string
  room_number: string | null

  device_id: string
  device_code: string

  /** How many events folded into this episode (one alert = one episode). */
  event_count: number
  /** The opening event arrived late — it describes the past, not the present. */
  delayed: boolean

  created_at: string
  last_event_at: string | null
  acknowledged_by: string | null
  acknowledged_at: string | null
  resolved_at: string | null
}

export interface SafetyAlertListResponse {
  total: number
  results: SafetyAlert[]
}

export interface WearableDevice {
  id: string
  device_code: string
  status: 'ACTIVE' | 'DISABLED' | 'RETIRED'
  hardware_id: string | null
  firmware_version: string | null
  battery_percent: number | null
  last_seen_at: string | null
  created_at: string
  /** Derived: holds a credential. */
  enrolled: boolean
  /** Derived: assigned AND reporting recently. An unassigned device in a
   *  drawer is idle, not offline. */
  online: boolean
  /** Derived: currently monitoring a patient. `online` cannot distinguish
   *  "free" from "assigned but silent", so this is separate. */
  assigned: boolean
}

export interface WearableDeviceListResponse {
  total: number
  results: WearableDevice[]
}

export interface DeviceAssignment {
  id: string
  device_id: string
  device_code: string
  patient_id: string
  encounter_id: string | null
  monitoring_profile: MonitoringProfile
  assigned_at: string
  unassigned_at: string | null
  battery_percent: number | null
  last_seen_at: string | null
  device_status: 'ACTIVE' | 'DISABLED' | 'RETIRED'
  device_online: boolean
}

export interface PatientAssignmentResponse {
  assignment: DeviceAssignment | null
}

export type SensorEventType =
  | 'POSSIBLE_FALL'
  | 'ABNORMAL_MOVEMENT'
  | 'UNEXPECTED_MOBILITY'
  | 'DEVICE_LOW_BATTERY'

export interface SensorEvent {
  id: string
  device_id: string
  assignment_id: string
  event_type: SensorEventType
  /** When the device detected it. */
  occurred_at: string
  /** When the backend received it. Differs from occurred_at after an outage. */
  received_at: string
  delayed: boolean
  metrics: Record<string, unknown>
}

export interface SensorEventListResponse {
  total: number
  results: SensorEvent[]
}
