import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Wifi } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { addWifiNetwork, listWifiNetworks, removeWifiNetwork } from '@/api/safety-monitoring'
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
import { ApiError } from '@/lib/api-client'
import type { WifiNetwork } from '@/types/safety-monitoring'

const WIFI_QUERY_KEY = ['wifi-networks']

/** Admins: the Wi-Fi networks every band knows. Bands pick up a change at
 *  their next check-in and join the strongest network they can see, so add a
 *  ward's Wi-Fi here before the bands move there. */
export function WifiNetworksSection() {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const { data } = useQuery({ queryKey: WIFI_QUERY_KEY, queryFn: listWifiNetworks })
  const remove = useMutation({
    mutationFn: (n: WifiNetwork) => removeWifiNetwork(n.id),
    onSuccess: (_r, n) => {
      void queryClient.invalidateQueries({ queryKey: WIFI_QUERY_KEY })
      toast.success(`${n.ssid} removed — bands forget it at their next check-in`)
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not remove the network'),
  })
  const networks = data?.items ?? []

  return (
    <section className="mt-10 space-y-3" data-testid="wifi-networks">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold">
            <Wifi className="h-5 w-5" />
            Wi-Fi networks
          </h2>
          <p className="text-sm text-muted-foreground">
            Every band learns these at its next check-in and joins the strongest one it can see. Bands use 2.4 GHz
            Wi-Fi only. Passwords are never shown again.
          </p>
        </div>
        <Button variant="outline" onClick={() => setAdding(true)} data-testid="wifi-add">
          <Plus className="h-4 w-4" />
          Add network
        </Button>
      </div>
      {networks.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          None yet. Bands use only the Wi-Fi they were set up with until you add one.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {networks.map((n) => (
            <li key={n.id} className="flex items-center justify-between gap-3 px-4 py-2" data-testid="wifi-network">
              <div>
                <p className="font-medium">{n.ssid}</p>
                <p className="text-xs text-muted-foreground">
                  {n.label !== n.ssid ? `${n.label} · ` : ''}
                  {n.security === 'EAP' ? `Enterprise, user ${n.username ?? ''}` : 'Password'}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Remove ${n.ssid}`}
                disabled={remove.isPending}
                onClick={() => remove.mutate(n)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <AddWifiDialog open={adding} onClose={() => setAdding(false)} />
    </section>
  )
}

function AddWifiDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient()
  const [ssid, setSsid] = useState('')
  const [label, setLabel] = useState('')
  const [enterprise, setEnterprise] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function close() {
    onClose()
    setSsid('')
    setLabel('')
    setEnterprise(false)
    setUsername('')
    setPassword('')
    add.reset()
  }

  const add = useMutation({
    mutationFn: () =>
      addWifiNetwork({
        label: label.trim(),
        ssid: ssid.trim(),
        security: enterprise ? 'EAP' : 'PSK',
        password,
        username: enterprise ? username.trim() : null,
      }),
    onSuccess: (n) => {
      void queryClient.invalidateQueries({ queryKey: WIFI_QUERY_KEY })
      toast.success(`${n.ssid} added — bands pick it up within about 5 minutes`)
      close()
    },
  })

  const valid =
    ssid.trim().length > 0 && (enterprise ? username.trim().length > 0 && password.length > 0 : password.length >= 8)

  return (
    <Dialog open={open} onOpenChange={(next) => !next && close()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a Wi-Fi network</DialogTitle>
          <DialogDescription>Type the name exactly as phones show it. Capitals and spaces matter.</DialogDescription>
        </DialogHeader>
        <form
          id="wifi-form"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault()
            if (valid) add.mutate()
          }}
        >
          <div className="space-y-2">
            <Label htmlFor="wifi-ssid">Network name</Label>
            <Input id="wifi-ssid" autoComplete="off" value={ssid} onChange={(e) => setSsid(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="wifi-label">Where it is (optional)</Label>
            <Input
              id="wifi-label"
              autoComplete="off"
              placeholder="Ward 3"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <label className="flex items-center gap-3 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-primary"
              checked={enterprise}
              onChange={(e) => setEnterprise(e.target.checked)}
            />
            Sign-in with a username (WPA2-Enterprise)
          </label>
          {enterprise && (
            <div className="space-y-2">
              <Label htmlFor="wifi-username">Username</Label>
              <Input
                id="wifi-username"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="wifi-password">Password</Label>
            <Input
              id="wifi-password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {add.isError && (
            <p className="text-sm text-destructive">
              {add.error instanceof Error ? add.error.message : 'Could not add the network'}
            </p>
          )}
        </form>
        <DialogFooter>
          <Button variant="outline" onClick={close}>
            Cancel
          </Button>
          <Button type="submit" form="wifi-form" disabled={!valid || add.isPending} data-testid="wifi-save">
            Add network
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
