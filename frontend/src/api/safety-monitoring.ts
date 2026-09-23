import { apiRequest } from '@/lib/api-client'
import type { AlertStatus, SafetyAlert, SafetyAlertListResponse } from '@/types/safety-monitoring'

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
