import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Link as LinkIcon, ShieldOff } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { createCareAccessToken, listCareAccessTokens, revokeCareAccessToken } from '@/api/patient-access'
import { Badge } from '@/components/ui/badge'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api-client'
import type { CareAccessTokenStatus } from '@/types/patient-access'

function tokenStatusBadge(status: CareAccessTokenStatus) {
  if (status === 'ACTIVE') return <Badge variant="secondary">Active</Badge>
  if (status === 'REVOKED') return <Badge variant="destructive">Revoked</Badge>
  return <Badge variant="outline">Expired</Badge>
}

export function CreateCareLinkDialog({ patientId }: { patientId: string }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [expiresInHours, setExpiresInHours] = useState('')
  const queryClient = useQueryClient()

  const tokensQuery = useQuery({
    queryKey: ['care-access-tokens', patientId],
    queryFn: () => listCareAccessTokens(patientId),
    enabled: open,
  })

  const createMutation = useMutation({
    mutationFn: () => {
      const hours = expiresInHours.trim() === '' ? undefined : Number(expiresInHours)
      return createCareAccessToken(patientId, hours)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['care-access-tokens', patientId] })
      // The Activity & Safety Timeline tab may already be open on this same
      // page — see PatientDetailPage.tsx's discharge mutation for the same fix.
      queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to create patient care link')
    },
  })

  const revokeMutation = useMutation({
    mutationFn: (tokenId: string) => revokeCareAccessToken(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['care-access-tokens', patientId] })
      queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
      toast.success('Link revoked — it no longer works')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to revoke link')
    },
  })

  const careUrl = createMutation.data ? `${window.location.origin}/care?token=${createMutation.data.token}` : null

  function handleOpenChange(nextOpen: boolean) {
    setOpen(nextOpen)
    if (!nextOpen) {
      createMutation.reset()
      setCopied(false)
      setExpiresInHours('')
    }
  }

  async function handleCopy() {
    if (!careUrl) return
    await navigator.clipboard.writeText(careUrl)
    setCopied(true)
    toast.success('Link copied')
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline" data-testid="care-link-open-dialog">
          <LinkIcon className="h-4 w-4" />
          Patient Care Link
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Patient care link</DialogTitle>
          <DialogDescription>
            Opens a read-only view of this patient's approved instructions — no login required.
          </DialogDescription>
        </DialogHeader>

        {careUrl ? (
          <div className="space-y-2">
            <Label htmlFor="care-url">
              Link (expires {new Date(createMutation.data!.expires_at).toLocaleString()})
            </Label>
            <div className="flex gap-2">
              <Input
                id="care-url"
                readOnly
                value={careUrl}
                onFocus={(e) => e.currentTarget.select()}
                data-testid="care-link-url"
              />
              <Button type="button" variant="outline" onClick={handleCopy}>
                {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              Shown once — it isn't retrievable again. Generate a new one if it's lost.
            </p>
          </div>
        ) : (
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-2">
              <Label htmlFor="expires-in-hours">Expires in (hours, optional)</Label>
              <Input
                id="expires-in-hours"
                type="number"
                min={1}
                placeholder="Default"
                value={expiresInHours}
                onChange={(e) => setExpiresInHours(e.target.value)}
              />
            </div>
            <Button
              onClick={() => createMutation.mutate()}
              disabled={createMutation.isPending}
              data-testid="care-link-generate-button"
            >
              {createMutation.isPending ? 'Generating…' : 'Generate link'}
            </Button>
          </div>
        )}

        {tokensQuery.data && tokensQuery.data.results.length > 0 && (
          <div className="space-y-2">
            <Label>Existing links</Label>
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
              {tokensQuery.data.results.map((token) => (
                <div
                  key={token.id}
                  className="flex items-center justify-between gap-2 text-sm"
                  data-testid="care-link-token-row"
                  data-status={token.status}
                >
                  <div className="flex items-center gap-2">
                    {tokenStatusBadge(token.status)}
                    <span className="text-muted-foreground">
                      expires {new Date(token.expires_at).toLocaleString()}
                    </span>
                  </div>
                  {token.status === 'ACTIVE' && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => revokeMutation.mutate(token.id)}
                      disabled={revokeMutation.isPending}
                      data-testid="care-link-revoke-button"
                    >
                      <ShieldOff className="h-4 w-4" />
                      Revoke
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
