import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Mail, ShieldOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { getAppAccess, inviteToApp, revokeAppAccess } from '@/api/patients'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AdherenceChart } from '@/features/patients/AdherenceChart'
import { ApiError } from '@/lib/api-client'
import { formatDate, formatDateTime } from '@/lib/format'
import type { AppAccessStatus } from '@/types/patients'

const STATUS_BADGE: Record<AppAccessStatus, { label: string; className: string }> = {
  NOT_INVITED: { label: 'Not invited', className: 'border-border text-muted-foreground' },
  INVITED: { label: 'Invite sent', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  ACTIVE: { label: 'Using the app', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  REVOKED: { label: 'Turned off', className: 'border-border bg-muted text-muted-foreground' },
  EXPIRED: { label: 'Ended after discharge', className: 'border-border bg-muted text-muted-foreground' },
}

/** Staff side of the patient app: contact, consent, invite, turn off.
 *  The app's content needs no entry here — it comes from approved instructions. */
export function PatientAppPanel({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient()
  const { data: access, isLoading } = useQuery({
    queryKey: ['patient-app-access', patientId],
    queryFn: () => getAppAccess(patientId),
  })

  const [email, setEmail] = useState('')
  const [consent, setConsent] = useState(false)
  const [fallbackLink, setFallbackLink] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    setEmail(access?.email ?? '')
    setConsent(!!access?.consent_at)
  }, [access?.email, access?.consent_at])

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ['patient-app-access', patientId] })
    queryClient.invalidateQueries({ queryKey: ['patient', patientId] })
    queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
  }

  const inviteMutation = useMutation({
    mutationFn: () => inviteToApp(patientId, { email: email.trim() || null, consent }),
    onSuccess: (result) => {
      refresh()
      setFallbackLink(result.link)
      setCopied(false)
      if (result.emailed) toast.success(`Invite emailed to ${result.access.email}`)
      else toast.warning(`Email not sent: ${result.problem ?? 'unknown problem'}`, { description: 'Copy the link below instead.' })
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not send the invite'),
  })

  const revokeMutation = useMutation({
    mutationFn: () => revokeAppAccess(patientId),
    onSuccess: () => {
      refresh()
      setFallbackLink(null)
      toast.success('Patient app turned off — they are signed out everywhere')
    },
    onError: (error) => toast.error(error instanceof ApiError ? error.message : 'Could not turn off the app'),
  })

  if (isLoading || !access) return <p className="text-sm text-muted-foreground">Loading…</p>

  const badge = STATUS_BADGE[access.status]
  const live = access.status === 'INVITED' || access.status === 'ACTIVE'
  const emailChanged = email.trim().toLowerCase() !== (access.email ?? '')
  const canInvite = !!email.trim() && consent && !inviteMutation.isPending

  return (
    <div className="space-y-3" data-testid="patient-app-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Patient app</p>
        <Badge variant="outline" className={badge.className} data-status={access.status}>
          {badge.label}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">
        The patient signs in from an emailed link and sees their medicines, visits and care instructions as you approve
        them. Emails never contain medical details.
      </p>

      {(access.invited_at || access.last_sign_in_at || access.access_expires_at) && (
        <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
          {access.invited_at && (
            <div>
              <dt className="text-muted-foreground">Last invite</dt>
              <dd>{formatDateTime(access.invited_at)}</dd>
            </div>
          )}
          {access.last_sign_in_at && (
            <div>
              <dt className="text-muted-foreground">Last sign-in</dt>
              <dd>{formatDateTime(access.last_sign_in_at)}</dd>
            </div>
          )}
          {access.access_expires_at && (
            <div>
              <dt className="text-muted-foreground">Works until</dt>
              <dd>{formatDate(access.access_expires_at)}</dd>
            </div>
          )}
        </dl>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="space-y-1">
          <Label htmlFor="patient-app-email" className="text-xs">
            Patient's email
          </Label>
          <Input
            id="patient-app-email"
            type="email"
            inputMode="email"
            autoComplete="off"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="name@example.com"
            data-testid="patient-app-email"
          />
        </div>
        <Button
          size="sm"
          className="h-9"
          disabled={!canInvite}
          onClick={() => inviteMutation.mutate()}
          data-testid="patient-app-invite"
        >
          <Mail className="h-4 w-4" />
          {inviteMutation.isPending
            ? 'Sending…'
            : access.status === 'NOT_INVITED' || emailChanged
              ? 'Send invite'
              : 'Send again'}
        </Button>
      </div>

      {!access.consent_at && (
        <label className="flex items-start gap-3 text-sm leading-snug">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            data-testid="patient-app-consent-panel"
          />
          <span>The patient agreed to use the SafeHaven app and to receive emails about it.</span>
        </label>
      )}

      {fallbackLink && (
        <div className="space-y-1 rounded-lg border border-dashed p-3">
          <p className="text-xs text-muted-foreground">
            The email did not go. Give the patient this sign-in link another way — it works once.
          </p>
          <div className="flex gap-2">
            <Input readOnly value={fallbackLink} className="font-mono text-xs" onFocus={(e) => e.currentTarget.select()} />
            <Button
              variant="outline"
              size="icon"
              aria-label="Copy link"
              onClick={() => {
                void navigator.clipboard.writeText(fallbackLink).then(() => setCopied(true))
              }}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      )}

      {(access.status === 'ACTIVE' || access.status === 'EXPIRED' || access.status === 'REVOKED') && (
        <AdherenceChart patientId={patientId} />
      )}

      {live && (
        <Button
          variant="ghost"
          size="sm"
          className="-ml-2 text-destructive hover:text-destructive"
          disabled={revokeMutation.isPending}
          onClick={() => revokeMutation.mutate()}
          data-testid="patient-app-revoke"
        >
          <ShieldOff className="h-4 w-4" />
          Turn off app access
        </Button>
      )}
    </div>
  )
}
