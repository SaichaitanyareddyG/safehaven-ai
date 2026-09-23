import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { BatteryFull, BatteryLow, Plus, Wifi, WifiOff } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { assignWearable, listWearableDevices } from '@/api/safety-monitoring'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SAFETY_ALERTS_QUERY_KEY } from '@/features/safety-monitoring/use-safety-alerts'
import { ApiError } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { MonitoringProfile, WearableDevice } from '@/types/safety-monitoring'

/**
 * Monitoring profiles, with the consequence of each spelled out.
 *
 * The descriptions are not decoration: RESTRICTED_MOBILITY turns on a detector
 * that a wrist sensor cannot make reliably, so whoever selects it should see
 * what it does and what it cannot promise before choosing it.
 */
const PROFILES: { value: MonitoringProfile; label: string; detail: string }[] = [
  {
    value: 'STANDARD',
    label: 'Standard',
    detail: 'Possible falls and abnormal repetitive movement.',
  },
  {
    value: 'FALL_RISK',
    label: 'Fall risk',
    detail: 'As standard, with abnormal movement raised to high priority.',
  },
  {
    value: 'RESTRICTED_MOBILITY',
    label: 'Restricted mobility',
    detail:
      'Also alerts on sustained walking-like movement. A wrist sensor cannot confirm a patient left the bed — alerts say "unexpected mobility", not "out of bed".',
  },
]

export function AssignDeviceDialog({ patientId }: { patientId: string }) {
  const [open, setOpen] = useState(false)
  const [deviceId, setDeviceId] = useState('')
  const [profile, setProfile] = useState<MonitoringProfile | ''>('')
  const queryClient = useQueryClient()

  const devicesQuery = useQuery({
    queryKey: ['wearable-devices'],
    queryFn: listWearableDevices,
    // Only fetch the fleet when the dialog is actually open.
    enabled: open,
  })

  const assign = useMutation({
    mutationFn: () => assignWearable(patientId, deviceId, profile as MonitoringProfile),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['wearable-assignment', patientId] })
      void queryClient.invalidateQueries({ queryKey: ['wearable-devices'] })
      // Assignment writes an audit event, and the Activity timeline may be
      // open on this same page (same fix as PatientDetailPage's discharge).
      void queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
      void queryClient.invalidateQueries({ queryKey: SAFETY_ALERTS_QUERY_KEY })
      toast.success('Safety monitoring started')
      setOpen(false)
      setDeviceId('')
      setProfile('')
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Failed to assign the device'),
  })

  // A device must be active, enrolled AND free to be offered.
  //
  // Unenrolled: holds no credential, so it can never report anything —
  // assigning it would create a false impression that the patient is
  // monitored.
  // Already assigned: it is monitoring someone else. The backend rejects this
  // with a 409, but offering it and then failing wastes a nurse's time at the
  // bedside, so it is filtered here too.
  const available = (devicesQuery.data?.results ?? []).filter(
    (d) => d.status === 'ACTIVE' && d.enrolled && !d.assigned,
  )
  const inUse = (devicesQuery.data?.results ?? []).filter(
    (d) => d.status === 'ACTIVE' && d.enrolled && d.assigned,
  ).length

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" data-testid="assign-device-trigger">
          <Plus className="h-4 w-4" />
          Assign device
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Assign a wearable</DialogTitle>
          <DialogDescription>
            The device starts monitoring on its next check-in. It is never told who the patient is.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <Label className="text-xs">Available devices</Label>
            {devicesQuery.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {!devicesQuery.isLoading && available.length === 0 && (
              <p className="text-sm text-muted-foreground" data-testid="no-devices-available">
                No enrolled devices are free.{' '}
                {inUse > 0
                  ? `${inUse} ${inUse === 1 ? 'device is' : 'devices are'} monitoring other patients.`
                  : 'Register and enrol a device first.'}
              </p>
            )}
            <div className="space-y-1">
              {available.map((device) => (
                <DeviceOption
                  key={device.id}
                  device={device}
                  selected={deviceId === device.id}
                  onSelect={() => setDeviceId(device.id)}
                />
              ))}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="monitoring-profile" className="text-xs">
              Monitoring profile
            </Label>
            {/* No default. Defaulting to Standard could silently give the wrong
                behaviour; defaulting to Restricted mobility would switch on an
                inferential detector nobody asked for. */}
            <Select value={profile} onValueChange={(v) => setProfile(v as MonitoringProfile)}>
              <SelectTrigger id="monitoring-profile" data-testid="monitoring-profile-select">
                <SelectValue placeholder="Choose a profile…" />
              </SelectTrigger>
              <SelectContent>
                {PROFILES.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {profile && (
              <p className="text-xs text-muted-foreground" data-testid="profile-detail">
                {PROFILES.find((p) => p.value === profile)?.detail}
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            onClick={() => assign.mutate()}
            disabled={!deviceId || !profile || assign.isPending}
            data-testid="confirm-assign-device"
          >
            Start monitoring
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeviceOption({
  device,
  selected,
  onSelect,
}: {
  device: WearableDevice
  selected: boolean
  onSelect: () => void
}) {
  const lowBattery = device.battery_percent !== null && device.battery_percent <= 20
  // Mirrors the backend's offline threshold closely enough to be useful
  // guidance here; the backend remains the authority once assigned.
  const stale =
    device.last_seen_at !== null &&
    Date.now() - new Date(device.last_seen_at).getTime() > 2 * 60 * 1000

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-sm',
        selected ? 'border-primary bg-primary/5' : 'hover:bg-muted/50',
      )}
      data-testid="device-option"
      data-device-code={device.device_code}
      data-selected={selected}
    >
      <span className="font-medium">{device.device_code}</span>
      <span className="flex items-center gap-3 text-xs text-muted-foreground">
        {device.battery_percent !== null && (
          <span className={cn('flex items-center gap-1', lowBattery && 'text-amber-700')}>
            {lowBattery ? <BatteryLow className="h-3 w-3" /> : <BatteryFull className="h-3 w-3" />}
            {device.battery_percent}%
          </span>
        )}
        {/* An unassigned device is idle, not offline, so this is information
            rather than an alarm. But it must be specific: a bare "Seen" for a
            device last heard from two days ago reads as healthy, and assigning
            it raises an offline alert seconds later. Showing WHEN lets a nurse
            pick a charged, awake device instead. */}
        <span className={cn('flex items-center gap-1', stale && 'text-amber-700')}>
          {device.last_seen_at ? (
            <>
              {stale ? <WifiOff className="h-3 w-3" /> : <Wifi className="h-3 w-3" />}
              {formatDistanceToNow(new Date(device.last_seen_at), { addSuffix: true })}
            </>
          ) : (
            <>
              <WifiOff className="h-3 w-3" />
              Never checked in
            </>
          )}
        </span>
      </span>
    </button>
  )
}
