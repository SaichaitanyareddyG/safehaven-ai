import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { BatteryLow, ShieldCheck, Wifi, WifiOff } from 'lucide-react'
import { toast } from 'sonner'

import { getPatientAssignment, unassignWearable } from '@/api/safety-monitoring'
import { Button } from '@/components/ui/button'
import { AssignDeviceDialog } from '@/features/safety-monitoring/AssignDeviceDialog'
import { MonitoringProfileBadge } from '@/features/safety-monitoring/AlertBadges'
import { SAFETY_ALERTS_QUERY_KEY } from '@/features/safety-monitoring/use-safety-alerts'
import { ApiError } from '@/lib/api-client'
import { cn } from '@/lib/utils'

/**
 * Wearable status for one patient, on the patient detail page.
 *
 * Deliberately small: this is "is this patient monitored, by what, and is it
 * working" — not device fleet management.
 */
export function WearableDevicePanel({
  patientId,
  patientIsActive,
}: {
  patientId: string
  patientIsActive: boolean
}) {
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ['wearable-assignment', patientId],
    queryFn: () => getPatientAssignment(patientId),
    // Battery and last-seen go stale, so refresh while the page is open. Much
    // slower than the alert queue: this is status, not an alarm.
    refetchInterval: 15_000,
  })

  const unassign = useMutation({
    mutationFn: () => unassignWearable(patientId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['wearable-assignment', patientId] })
      void queryClient.invalidateQueries({ queryKey: ['wearable-devices'] })
      void queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
      void queryClient.invalidateQueries({ queryKey: SAFETY_ALERTS_QUERY_KEY })
      toast.success('Monitoring stopped — device returned to the pool')
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to unassign the device'),
  })

  const assignment = data?.assignment ?? null

  return (
    <div className="space-y-3" data-testid="wearable-device-panel">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium">Safety Monitoring</p>
          <p className="text-xs text-muted-foreground">
            A wearable reports falls and unusual movement. It observes movement only — it does not
            diagnose a cause.
          </p>
        </div>
        {/* Discharge already ends monitoring automatically, so a discharged
            patient has nothing to assign. */}
        {!assignment && patientIsActive && <AssignDeviceDialog patientId={patientId} />}
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {!isLoading && !assignment && (
        <p className="text-sm text-muted-foreground" data-testid="no-wearable-assigned">
          {patientIsActive
            ? 'No wearable assigned.'
            : 'No wearable assigned. Monitoring ended automatically at discharge.'}
        </p>
      )}

      {assignment && (
        <div
          className="flex items-center justify-between rounded-lg border px-3 py-2"
          data-testid="wearable-assignment-row"
          data-device-code={assignment.device_code}
        >
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
              <span className="text-sm font-medium">{assignment.device_code}</span>
              <MonitoringProfileBadge profile={assignment.monitoring_profile} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              {/* Online state is derived from the last check-in, so it tells a
                  nurse whether to trust the absence of alerts. */}
              <span
                className={cn(
                  'flex items-center gap-1',
                  assignment.device_online ? 'text-emerald-700' : 'font-medium text-red-600',
                )}
                data-testid="wearable-online-state"
                data-online={assignment.device_online}
              >
                {assignment.device_online ? (
                  <>
                    <Wifi className="h-3 w-3" />
                    Connected
                  </>
                ) : (
                  <>
                    <WifiOff className="h-3 w-3" />
                    Not reporting
                  </>
                )}
              </span>
              {assignment.battery_percent !== null && (
                <span
                  className={cn(
                    'flex items-center gap-1',
                    assignment.battery_percent <= 20 && 'text-amber-700',
                  )}
                  data-testid="wearable-battery"
                >
                  {assignment.battery_percent <= 20 && <BatteryLow className="h-3 w-3" />}
                  Battery {assignment.battery_percent}%
                </span>
              )}
              <span>
                {assignment.last_seen_at
                  ? `Last check-in ${formatDistanceToNow(new Date(assignment.last_seen_at), { addSuffix: true })}`
                  : 'No check-in yet'}
              </span>
            </div>
          </div>

          <Button
            variant="outline"
            size="sm"
            disabled={unassign.isPending}
            onClick={() => unassign.mutate()}
            data-testid="unassign-device"
          >
            Unassign
          </Button>
        </div>
      )}
    </div>
  )
}
