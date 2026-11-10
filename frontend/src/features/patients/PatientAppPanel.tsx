import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Mail, PauseCircle, PlayCircle, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { deactivateAppAccess, deleteAppAccess, getAppAccess, inviteToApp, reactivateAppAccess } from '@/api/patients'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AdherenceChart } from '@/features/patients/AdherenceChart'
import { CaregiversSection } from '@/features/patients/CaregiversSection'
import { ApiError } from '@/lib/api-client'
import { formatDate, formatDateTime } from '@/lib/format'
import type { AppAccessStatus } from '@/types/patients'

const STATUS_BADGE: Record<AppAccessStatus, { label: string; className: string }> = {
  NOT_INVITED: { label: 'Not invited', className: 'border-border text-muted-foreground' },
  INVITED: { label: 'Invite sent', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  ACTIVE: { label: 'Using the app', className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  REVOKED: { label: 'Deactivated', className: 'border-amber-200 bg-amber-50 text-amber-800' },
  EXPIRED: { label: 'Ended after discharge', className: 'border-border bg-muted text-muted-foreground' },
}

/** Staff side of the patient app: contact, consent, invite, deactivate /
 *  reactivate (password kept) or delete the login (record and history stay).
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

  const failed = (what: string) => (error: Error) =>
    toast.error(error instanceof ApiError ? error.message : `Could not ${what}`)
  const deactivate = useMutation({
    mutationFn: () => deactivateAppAccess(patientId),
    onSuccess: () => {
      refresh()
      setFallbackLink(null)
      toast.success('App account deactivated — signed out everywhere, reminders stopped')
    },
    onError: failed('deactivate the account'),
  })
  const reactivate = useMutation({
    mutationFn: () => reactivateAppAccess(patientId),
    onSuccess: () => {
      refresh()
      toast.success('App account reactivated — the patient signs in with the same password')
    },
    onError: failed('reactivate the account'),
  })
  const remove = useMutation({
    mutationFn: () => deleteAppAccess(patientId),
    onSuccess: () => {
      refresh()
      setFallbackLink(null)
      toast.success('App account deleted. The patient record and history are kept.')
    },
    onError: failed('delete the account'),
  })
  const busy = deactivate.isPending || reactivate.isPending || remove.isPending

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
        The patient creates a password from the emailed invite and sees their medicines, visits and care instructions
        as you approve them. Emails never contain medical details.
      </p>
      {access.status === 'REVOKED' && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="patient-app-deactivated-note">
          {access.deactivated_by_patient
            ? 'The patient deactivated their own account. Signing in again switches it back on.'
            : access.has_password
              ? 'Deactivated by staff. The patient cannot sign in until you reactivate it; their password is kept.'
              : 'Deactivated by staff before a password was created. Send a new invite to switch it back on.'}
        </p>
      )}

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

      {access.consent_at && <CaregiversSection patientId={patientId} caregivers={access.caregivers ?? []} />}

      {(live || access.status === 'REVOKED') && (
        <div className="-ml-2 flex flex-wrap gap-1">
          {live && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => deactivate.mutate()}
              data-testid="patient-app-deactivate"
            >
              <PauseCircle className="h-4 w-4" />
              Deactivate
            </Button>
          )}
          {access.status === 'REVOKED' && access.has_password && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => reactivate.mutate()}
              data-testid="patient-app-reactivate"
            >
              <PlayCircle className="h-4 w-4" />
              Reactivate
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            disabled={busy}
            onClick={() => {
              if (
                window.confirm(
                  "Delete this patient's app account? Their login, password and calendar link are removed for good. " +
                    'The patient record, dose history and questions are kept. You can invite them again later.',
                )
              )
                remove.mutate()
            }}
            data-testid="patient-app-delete"
          >
            <Trash2 className="h-4 w-4" />
            Delete account
          </Button>
        </div>
      )}
    </div>
  )
}
