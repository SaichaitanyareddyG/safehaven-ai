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
