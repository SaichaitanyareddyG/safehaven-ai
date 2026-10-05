import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Plus, Watch } from 'lucide-react'
import { useState } from 'react'

import { listWearableDevices, pairWearable } from '@/api/safety-monitoring'
import { AppLayout } from '@/components/AppLayout'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { WearableDevice } from '@/types/safety-monitoring'

const DEVICES_QUERY_KEY = ['wearable-devices']

/**
 * The ward's wearable bands, and the one place a new band is added.
 *
 * Adding is device-initiated: a new band shows a six-digit code on its screen,
 * staff type it here with the label printed on the band, and the band finishes
 * enrolling by itself. No terminal, no USB, no enrolment code to copy around.
 */
export function DevicesPage() {
  const [adding, setAdding] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: DEVICES_QUERY_KEY,
    queryFn: listWearableDevices,
    refetchInterval: 10_000,
  })
  const devices = data?.results ?? []

  return (
    <AppLayout>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Bands</h1>
          <p className="text-sm text-muted-foreground">
            Wearable bands on this ward. Assign a band to a patient from the patient's page.
          </p>
        </div>
        <Button onClick={() => setAdding(true)} data-testid="add-device">
          <Plus className="h-4 w-4" />
          Add device
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : devices.length === 0 ? (
        <p className="text-sm text-muted-foreground">No devices yet. Switch on a new band and click Add device.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Band</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Battery</TableHead>
              <TableHead className="hidden sm:table-cell">Last check-in</TableHead>
              <TableHead className="hidden md:table-cell">Firmware</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {devices.map((d) => (
              <TableRow key={d.id} data-testid="device-row">
                <TableCell className="font-medium">
                  {d.device_code}
                  <span className="block text-xs font-normal text-muted-foreground sm:hidden">
                    {d.last_seen_at ? `Seen ${formatDistanceToNow(new Date(d.last_seen_at), { addSuffix: true })}` : 'Never seen'}
                  </span>
                </TableCell>
                <TableCell>
                  <DeviceState device={d} />
                </TableCell>
                <TableCell
                  className={d.battery_percent != null && d.battery_percent <= 20 ? 'font-medium text-amber-700' : undefined}
                >
                  {d.battery_percent != null ? `${d.battery_percent}%` : '—'}
                </TableCell>
                <TableCell className="hidden sm:table-cell">
                  {d.last_seen_at
                    ? formatDistanceToNow(new Date(d.last_seen_at), { addSuffix: true })
                    : 'Never'}
                </TableCell>
                <TableCell className="hidden text-muted-foreground md:table-cell">{d.firmware_version ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <AddDeviceDialog open={adding} onOpenChange={setAdding} />
    </AppLayout>
  )
}

function DeviceState({ device }: { device: WearableDevice }) {
  if (device.status !== 'ACTIVE') {
    return <Badge variant="outline">{device.status === 'RETIRED' ? 'Retired' : 'Switched off'}</Badge>
  }
  if (!device.enrolled) return <Badge variant="outline">Waiting to finish pairing</Badge>
  if (device.assigned && device.charging) {
    // Off the wrist and detection paused: say plainly that nobody is watched.
    return <Badge variant="destructive">Charging — not monitoring</Badge>
  }
  if (device.charging) return <Badge variant="secondary">Charging</Badge>
  if (device.assigned) {
    return device.online ? (
      <Badge>Monitoring a patient</Badge>
    ) : (
      <Badge variant="destructive">Assigned, not checking in</Badge>
    )
  }
  return <Badge variant="secondary">Ready to assign</Badge>
}

function AddDeviceDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient()
  const [code, setCode] = useState('')
  const [label, setLabel] = useState('')

  const pair = useMutation({
    mutationFn: () => pairWearable(code.replace(/\s/g, ''), label.trim()),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: DEVICES_QUERY_KEY })
    },
  })

  function close(next: boolean) {
    onOpenChange(next)
    if (!next) {
      setCode('')
      setLabel('')
      pair.reset()
    }
  }

  const digits = code.replace(/\s/g, '')
  const valid = /^\d{6}$/.test(digits) && label.trim().length >= 3

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Watch className="h-5 w-5" />
            Add a device
          </DialogTitle>
          <DialogDescription>
            Switch on the new band. It shows a six-digit code on its screen — type it here.
          </DialogDescription>
        </DialogHeader>

        {pair.isSuccess ? (
          <Alert>
            <AlertDescription>
              <strong>{pair.data.device_code}</strong> added. The band finishes setting itself up in a few
              seconds and then shows “Not paired yet” — assign it to a patient from their page.
            </AlertDescription>
          </Alert>
        ) : (
          <form
            className="space-y-4"
            id="add-device-form"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) pair.mutate()
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="pairing-code">Code on the band's screen</Label>
              <Input
                id="pairing-code"
                inputMode="numeric"
                autoComplete="off"
                placeholder="482 913"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="font-mono text-lg tracking-widest"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="device-label">Label printed on the band</Label>
              <Input
                id="device-label"
                autoComplete="off"
                placeholder="SH-WEAR-002"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
              />
            </div>
            {pair.isError && (
              <p className="text-sm text-destructive">
                {pair.error instanceof Error ? pair.error.message : 'Could not add the device'}
              </p>
            )}
          </form>
        )}

        <DialogFooter>
          {pair.isSuccess ? (
            <Button onClick={() => close(false)}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={() => close(false)}>
                Cancel
              </Button>
              <Button type="submit" form="add-device-form" disabled={!valid || pair.isPending}>
                Add device
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
