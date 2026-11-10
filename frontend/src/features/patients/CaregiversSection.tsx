import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Mail, PauseCircle, PlayCircle, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { deactivateCaregiver, deleteCaregiver, inviteCaregiver, reactivateCaregiver } from '@/api/patients'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ApiError } from '@/lib/api-client'
import { formatDateTime } from '@/lib/format'
import type { Caregiver } from '@/types/patients'

const STATUS: Record<Caregiver['status'], string> = {
  NOT_INVITED: 'Not invited',
  INVITED: 'Invite sent',
  ACTIVE: 'Using the app',
  REVOKED: 'Deactivated',
  EXPIRED: 'Ended after discharge',
}

/** Family members or carers who get their own login to the patient's app —
 *  only with the patient's agreement. Each has their own on/off switch. */
export function CaregiversSection({ patientId, caregivers }: { patientId: string; caregivers: Caregiver[] }) {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [relationship, setRelationship] = useState('')
  const [email, setEmail] = useState('')
  const [consent, setConsent] = useState(false)
  const [fallbackLink, setFallbackLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ['patient-app-access', patientId] })
    queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
  }

  const invite = useMutation({
    mutationFn: (payload: { email: string; name: string; relationship: string | null }) =>
      inviteCaregiver(patientId, { ...payload, consent: true }),
    onSuccess: (result) => {
      refresh()
      setFallbackLink(result.link)
      setCopied(false)
      setAdding(false)
      setName('')
      setRelationship('')
      setEmail('')
      setConsent(false)
      if (result.emailed) toast.success(`Invite emailed to ${result.caregiver.email}`)
      else toast.warning(`Email not sent: ${result.problem ?? 'unknown problem'}`, { description: 'Copy the link below instead.' })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not invite the caregiver'),
  })

  const failed = (what: string) => (error: Error) =>
    toast.error(error instanceof ApiError ? error.message : `Could not ${what}`)
  const deactivate = useMutation({
    mutationFn: (id: string) => deactivateCaregiver(patientId, id),
    onSuccess: (c) => {
      refresh()
      toast.success(`${c.display_name ?? 'Caregiver'}'s account deactivated`)
    },
    onError: failed('deactivate the account'),
  })
  const reactivate = useMutation({
    mutationFn: (id: string) => reactivateCaregiver(patientId, id),
    onSuccess: (c) => {
      refresh()
      toast.success(`${c.display_name ?? 'Caregiver'}'s account reactivated`)
    },
    onError: failed('reactivate the account'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteCaregiver(patientId, id),
    onSuccess: () => {
      refresh()
      toast.success('Caregiver account deleted')
    },
    onError: failed('delete the account'),
  })
  const busy = deactivate.isPending || reactivate.isPending || remove.isPending

  const valid = name.trim() && /^\S+@\S+\.\S+$/.test(email.trim()) && consent

  return (
    <div className="space-y-2 rounded-lg border p-3" data-testid="caregivers-section">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Family & caregivers</p>
        {!adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="caregiver-add">
            <UserPlus className="h-4 w-4" />
            Add caregiver
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Someone who helps at home gets their own sign-in and sees the same medicines, dose times and appointments.
      </p>

      {caregivers.map((c) => {
        const live = c.status === 'INVITED' || c.status === 'ACTIVE'
        return (
          <div key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-2" data-testid="caregiver-row">
            <div className="min-w-0 text-sm">
              <p className="font-medium">
                {c.display_name}
                {c.relationship && <span className="font-normal text-muted-foreground"> · {c.relationship}</span>}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {c.email}
                {c.last_sign_in_at && ` · last sign-in ${formatDateTime(c.last_sign_in_at)}`}
              </p>
            </div>
            <div className="flex items-center gap-1">
              <Badge variant="outline">{STATUS[c.status]}</Badge>
              <Button
                variant="ghost"
                size="sm"
                disabled={invite.isPending}
                onClick={() => invite.mutate({ email: c.email ?? '', name: c.display_name ?? '', relationship: c.relationship })}
                aria-label={`Send ${c.display_name} a new invite`}
              >
                <Mail className="h-4 w-4" />
                {live ? 'Resend' : 'New invite'}
              </Button>
              {live && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => deactivate.mutate(c.id)}
                  aria-label={`Deactivate ${c.display_name}'s account`}
                >
                  <PauseCircle className="h-4 w-4" />
                  Deactivate
                </Button>
              )}
              {c.status === 'REVOKED' && c.has_password && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => reactivate.mutate(c.id)}
                  aria-label={`Reactivate ${c.display_name}'s account`}
                >
                  <PlayCircle className="h-4 w-4" />
                  Reactivate
                </Button>
              )}
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive hover:text-destructive"
                disabled={busy}
                onClick={() => {
                  if (window.confirm(`Delete ${c.display_name}'s app account for good?`)) remove.mutate(c.id)
                }}
                aria-label={`Delete ${c.display_name}'s account`}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )
      })}

      {adding && (
        <div className="space-y-3 rounded-md border border-dashed p-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="cg-name" className="text-xs">
                Name
              </Label>
              <Input id="cg-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="cg-rel" className="text-xs">
                Relationship
              </Label>
              <Input id="cg-rel" value={relationship} onChange={(e) => setRelationship(e.target.value)} placeholder="e.g. daughter" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="cg-email" className="text-xs">
                Email
              </Label>
              <Input id="cg-email" type="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
          </div>
          <label className="flex items-start gap-3 text-sm leading-snug">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              data-testid="caregiver-consent"
            />
            <span>The patient agreed to share their care information with this person.</span>
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!valid || invite.isPending}
              onClick={() => invite.mutate({ email: email.trim(), name: name.trim(), relationship: relationship.trim() || null })}
              data-testid="caregiver-invite"
            >
              {invite.isPending ? 'Sending…' : 'Send invite'}
            </Button>
          </div>
        </div>
      )}

      {fallbackLink && (
        <div className="space-y-1 rounded-md border border-dashed p-3">
          <p className="text-xs text-muted-foreground">The email did not go. Give the caregiver this sign-in link another way — it works once.</p>
          <div className="flex gap-2">
            <Input readOnly value={fallbackLink} className="font-mono text-xs" onFocus={(e) => e.currentTarget.select()} />
            <Button
              variant="outline"
              size="icon"
              aria-label="Copy link"
              onClick={() => void navigator.clipboard.writeText(fallbackLink).then(() => setCopied(true))}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
