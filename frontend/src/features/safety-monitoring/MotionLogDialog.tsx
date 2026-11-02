import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { format } from 'date-fns'
import { toast } from 'sonner'

import { labelMotionEvent, listMotionEvents } from '@/api/safety-monitoring'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ApiError } from '@/lib/api-client'
import type { MotionEvent, MotionLabel, MotionOutcome, WearableDevice } from '@/types/safety-monitoring'

const OUTCOME: Record<MotionOutcome, { label: string; className: string }> = {
  ALERT: { label: 'Alert', className: 'border-red-200 bg-red-50 text-red-800' },
  CHECK: { label: 'Asked', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  NONE: { label: 'Ignored', className: 'border-border text-muted-foreground' },
  MUTED: { label: 'Muted', className: 'border-border text-muted-foreground' },
}

const LABELS: { value: MotionLabel; label: string }[] = [
  { value: 'FLIP', label: 'Flip / turn' },
  { value: 'DROP', label: 'Band dropped' },
  { value: 'FALL', label: 'Real fall' },
  { value: 'ACTIVITY', label: 'Everyday movement' },
  { value: 'OTHER', label: 'Other' },
]

/** The band's fall-detector log: every movement it reacted to, in numbers,
 *  and what really happened as staff mark it. The counts at the top show how
 *  each kind was treated, which is what the detector is tuned against. */
export function MotionLogDialog({ device, onClose }: { device: WearableDevice | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const key = ['motion-events', device?.id]
  const { data: events, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => listMotionEvents(device!.id),
    enabled: !!device,
    refetchInterval: 15_000,
  })
  const label = useMutation({
    mutationFn: ({ id, value }: { id: string; value: MotionLabel | null }) => labelMotionEvent(id, value),
    onSuccess: (row) =>
      queryClient.setQueryData<MotionEvent[]>(key, (old) => old?.map((e) => (e.id === row.id ? row : e))),
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not save the label'),
  })

  const rows = events ?? []
  const summary = LABELS.map(({ value, label: name }) => {
    const of = rows.filter((e) => e.label === value)
    return {
      name,
      total: of.length,
      alert: of.filter((e) => e.outcome === 'ALERT').length,
      asked: of.filter((e) => e.outcome === 'CHECK').length,
    }
  }).filter((s) => s.total > 0)

  return (
    <Dialog open={!!device} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>Detector log — {device?.device_code}</DialogTitle>
          <DialogDescription>
            Every movement the fall detector reacted to, measured by the band. Mark what really happened; the counts
            show how each kind was treated.
          </DialogDescription>
        </DialogHeader>

        {summary.length > 0 && (
          <div className="flex flex-wrap gap-2" data-testid="motion-summary">
            {summary.map((s) => (
              <div key={s.name} className="rounded-lg border px-3 py-2 text-sm">
                <span className="font-medium">{s.name}</span>: {s.total} — alert {s.alert}, asked {s.asked}, ignored{' '}
                {s.total - s.alert - s.asked}
              </div>
            ))}
          </div>
        )}

        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing yet. The band sends each event after its next check-in (firmware 0.7.7 or newer).
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Band did</TableHead>
                <TableHead className="text-right">Free-fall</TableHead>
                <TableHead className="text-right">Hit</TableHead>
                <TableHead className="text-right">Turned</TableHead>
                <TableHead className="text-right">Spin</TableHead>
                <TableHead className="text-right">Facing</TableHead>
                <TableHead className="text-right">Still after</TableHead>
                <TableHead>What happened</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((e) => (
                <TableRow key={e.id} data-testid="motion-row">
                  <TableCell className="whitespace-nowrap">{format(new Date(e.occurred_at), 'd MMM HH:mm:ss')}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={OUTCOME[e.outcome].className}>
                      {OUTCOME[e.outcome].label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    {e.freefall_ms > 0 ? `${e.freefall_ms} ms (~${Math.round(e.drop_cm)} cm)` : '—'}
                  </TableCell>
                  <TableCell className="text-right">{e.peak_g.toFixed(1)} g</TableCell>
                  <TableCell className="text-right whitespace-nowrap">
                    {Math.round(e.turned_deg)}° ({e.axis})
                  </TableCell>
                  <TableCell className="text-right whitespace-nowrap">{Math.round(e.spin_dps)}°/s</TableCell>
                  <TableCell className="text-right">{Math.round(e.tilt_change_deg)}°</TableCell>
                  <TableCell className="text-right">{(e.still_ms / 1000).toFixed(1)} s</TableCell>
                  <TableCell>
                    <select
                      aria-label="What happened"
                      className="h-8 rounded-md border bg-background px-2 text-sm"
                      value={e.label ?? ''}
                      onChange={(ev) =>
                        label.mutate({ id: e.id, value: (ev.target.value || null) as MotionLabel | null })
                      }
                      data-testid="motion-label"
                    >
                      <option value="">—</option>
                      {LABELS.map((l) => (
                        <option key={l.value} value={l.value}>
                          {l.label}
                        </option>
                      ))}
                    </select>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="text-xs text-muted-foreground">
          Free-fall: how long the band was weightless, and the height that drop equals. Turned: degrees in the 2 s
          around the hit, and the band&apos;s axis it turned around most. Facing: how far it ended up from where it
          faced before.
        </p>
      </DialogContent>
    </Dialog>
  )
}
