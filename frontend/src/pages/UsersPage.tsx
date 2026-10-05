import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Check, Copy, Mail, MailWarning, Search, Send, UserPlus } from 'lucide-react'
import { useState } from 'react'

import { createUser, listUsers, removeInvite, sendPasswordLink, updateUser } from '@/api/admin-users'
import { AppLayout } from '@/components/AppLayout'
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
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'
import type { AdminUser, InviteResponse, Role } from '@/types/auth'

const USERS_QUERY_KEY = ['admin-users']

/**
 * Admin only: who can sign in to this dashboard. A new user is emailed an
 * invite link (single use, expires) to choose their own password — the admin
 * never sees it. If the email fails the admin can copy the link instead.
 * Accounts are switched off, never deleted, so the audit trail keeps a real
 * person behind every action.
 */
export function UsersPage() {
  const { user: me } = useAuth()
  const [search, setSearch] = useState('')
  const [issued, setIssued] = useState<{ response: InviteResponse; reason: 'created' | 'resent' } | null>(null)
  const [confirming, setConfirming] = useState<AdminUser | null>(null)
  const { data, isLoading } = useQuery({ queryKey: USERS_QUERY_KEY, queryFn: listUsers })

  const users = (data ?? []).filter((u) =>
    `${u.full_name} ${u.email}`.toLowerCase().includes(search.trim().toLowerCase()),
  )

  return (
    <AppLayout>
      <div className="mb-6 flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Users</h1>
        <p className="text-sm text-muted-foreground">Who can sign in to this ward dashboard. Only admins see this page.</p>
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <section aria-label="All users" className="min-w-0 flex-[999_1_560px] overflow-hidden rounded-2xl bg-white shadow-sm ring-1 ring-black/5">
          <div className="flex flex-wrap items-center gap-3 border-b px-5 py-4">
            <span className="font-semibold">
              {data ? `${data.length} user${data.length === 1 ? '' : 's'}` : 'Users'}
            </span>
            <div className="relative ml-auto w-full sm:w-60">
              <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                aria-label="Search users"
                placeholder="Name or email"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="h-10 pl-9"
              />
            </div>
          </div>

          {isLoading ? (
            <div className="space-y-2 p-5">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <Table className="min-w-[640px]">
                <TableHeader>
                  <TableRow>
                    <TableHead className="pl-5">Name</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Last sign-in</TableHead>
                    <TableHead className="pr-5 text-right">
                      <span className="sr-only">Actions</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {users.map((u) => (
                    <UserRow
                      key={u.id}
                      user={u}
                      isMe={u.id === me?.id}
                      onLinkSent={(response) => setIssued({ response, reason: 'resent' })}
                      onDeactivate={() => setConfirming(u)}
                    />
                  ))}
                  {users.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                        No one matches “{search}”.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </section>

        <AddUserForm onCreated={(response) => setIssued({ response, reason: 'created' })} />
      </div>

      <InviteDialog issued={issued} onClose={() => setIssued(null)} />
      <DeactivateDialog user={confirming} onClose={() => setConfirming(null)} />
    </AppLayout>
  )
}

function UserRow({
  user,
  isMe,
  onLinkSent,
  onDeactivate,
}: {
  user: AdminUser
  isMe: boolean
  onLinkSent: (r: InviteResponse) => void
  onDeactivate: () => void
}) {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })

  const changeRole = useMutation({ mutationFn: (role: Role) => updateUser(user.id, { role }), onSuccess: refresh })
  const reactivate = useMutation({ mutationFn: () => updateUser(user.id, { is_active: true }), onSuccess: refresh })
  const sendLink = useMutation({
    mutationFn: () => sendPasswordLink(user.id),
    onSuccess: (r) => {
      void refresh()
      onLinkSent(r)
    },
  })
  const linkLabel = user.must_change_password ? 'Resend invite' : 'Send password reset link'
  const neverJoined = user.must_change_password && !user.last_login_at

  return (
    <TableRow data-testid="user-row" className={cn(!user.is_active && 'text-muted-foreground')}>
      <TableCell className="pl-5">
        <div className="flex min-w-0 flex-col">
          <span className="font-medium text-foreground">
            {user.full_name}
            {isMe && <span className="font-normal text-muted-foreground"> (you)</span>}
          </span>
          <span className="block max-w-[260px] truncate text-sm text-muted-foreground" title={user.email}>
            {user.email}
          </span>
        </div>
      </TableCell>
      <TableCell>
        {isMe || !user.is_active ? (
          <RolePill role={user.role} muted={!user.is_active} />
        ) : (
          <select
            aria-label={`Role for ${user.full_name}`}
            value={user.role}
            disabled={changeRole.isPending}
            onChange={(e) => changeRole.mutate(e.target.value as Role)}
            className="h-9 rounded-lg border border-input bg-white px-2 text-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <option value="clinician">Clinician</option>
            <option value="admin">Admin</option>
          </select>
        )}
      </TableCell>
      <TableCell>
        <Status user={user} />
      </TableCell>
      <TableCell>
        {user.last_login_at ? formatDistanceToNow(new Date(user.last_login_at), { addSuffix: true }) : 'Never'}
      </TableCell>
      <TableCell className="pr-5 text-right">
        {isMe ? (
          <span className="text-muted-foreground">—</span>
        ) : user.is_active ? (
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => sendLink.mutate()}
              disabled={sendLink.isPending}
              aria-label={`${linkLabel} to ${user.full_name}`}
              title={linkLabel}
            >
              <Send className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onDeactivate}
              className="border-red-200 text-red-700 hover:bg-red-50 hover:text-red-800"
            >
              {neverJoined ? 'Remove invite' : 'Deactivate'}
            </Button>
          </div>
        ) : (
          <Button variant="outline" size="sm" onClick={() => reactivate.mutate()} disabled={reactivate.isPending}>
            Reactivate
          </Button>
        )}
      </TableCell>
    </TableRow>
  )
}

function RolePill({ role, muted }: { role: Role; muted?: boolean }) {
  return (
    <span
      className={cn(
        'rounded-md px-2.5 py-1 text-[13px] font-semibold',
        muted ? 'bg-muted text-muted-foreground' : role === 'admin' ? 'bg-[#143440] text-[#7CC3DB]' : 'bg-[#E2F0F5] text-[#0B5068]',
      )}
    >
      {role === 'admin' ? 'Admin' : 'Clinician'}
    </span>
  )
}

function Status({ user }: { user: AdminUser }) {
  const [dot, text, label] = !user.is_active
    ? ['bg-[#9AA5A8]', '', 'Deactivated']
    : user.must_change_password
      ? ['bg-[#F59E3D]', 'text-[#7A4200]', 'Invited']
      : ['bg-[#0F6383]', 'text-[#0B5068]', 'Active']
  return (
    <span className={cn('inline-flex items-center gap-1.5', text)}>
      <span className={cn('h-2 w-2 rounded-full', dot)} aria-hidden="true" />
      {label}
    </span>
  )
}

function AddUserForm({ onCreated }: { onCreated: (r: InviteResponse) => void }) {
  const queryClient = useQueryClient()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<Role>('clinician')

  const create = useMutation({
    mutationFn: () => createUser({ full_name: fullName.trim(), email: email.trim(), role }),
    onSuccess: (response) => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      setFullName('')
      setEmail('')
      setRole('clinician')
      onCreated(response)
    },
  })

  const valid = fullName.trim().length > 0 && /^\S+@\S+\.\S+$/.test(email.trim())

  return (
    <form
      aria-labelledby="add-user-title"
      className="flex min-w-0 flex-[1_1_320px] flex-col gap-4 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-black/5"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) create.mutate()
      }}
    >
      <h2 id="add-user-title" className="flex items-center gap-2 text-lg font-semibold">
        <UserPlus className="h-5 w-5 text-[#0F6383]" />
        Add a user
      </h2>
      <div className="space-y-2">
        <Label htmlFor="new-user-name">Full name</Label>
        <Input id="new-user-name" autoComplete="off" value={fullName} onChange={(e) => setFullName(e.target.value)} className="h-11" />
      </div>
      <div className="space-y-2">
        <Label htmlFor="new-user-email">Work email</Label>
        <Input
          id="new-user-email"
          type="email"
          autoComplete="off"
          placeholder="name@hospital.org"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="h-11"
        />
      </div>
      <fieldset className="space-y-2">
        <legend className="mb-2 text-sm font-medium">Role</legend>
        <RoleOption value="clinician" current={role} onChange={setRole} title="Clinician" text="Alerts, patients, bands, medication checks" />
        <RoleOption value="admin" current={role} onChange={setRole} title="Admin" text="Everything, plus adding and removing users" />
      </fieldset>
      {create.isError && (
        <p className="text-sm text-destructive">
          {create.error instanceof Error ? create.error.message : 'Could not create the user'}
        </p>
      )}
      <Button type="submit" disabled={!valid || create.isPending} className="h-11" data-testid="create-user">
        {create.isPending ? 'Sending invite…' : 'Send invite'}
      </Button>
      <p className="text-sm leading-relaxed text-muted-foreground">
        They get an email with a link to choose their own password. It works once, for 24 hours.
      </p>
    </form>
  )
}

function RoleOption({
  value,
  current,
  onChange,
  title,
  text,
}: {
  value: Role
  current: Role
  onChange: (r: Role) => void
  title: string
  text: string
}) {
  const checked = value === current
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-3 rounded-xl border-[1.5px] px-3.5 py-3',
        checked ? 'border-[#0F6383] bg-[#F2F8FA]' : 'border-input',
      )}
    >
      <input
        type="radio"
        name="new-user-role"
        value={value}
        checked={checked}
        onChange={() => onChange(value)}
        className="mt-0.5 h-4.5 w-4.5 accent-[#0F6383]"
      />
      <span className="flex flex-col">
        <span className="font-medium">{title}</span>
        <span className="text-sm text-muted-foreground">{text}</span>
      </span>
    </label>
  )
}

function InviteDialog({
  issued,
  onClose,
}: {
  issued: { response: InviteResponse; reason: 'created' | 'resent' } | null
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  if (!issued) return null
  const { user, link, emailed, email_problem: problem } = issued.response
  const first = user.full_name.split(' ')[0]
  const invite = user.must_change_password
  const close = () => {
    setCopied(false)
    onClose()
  }

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="grid-cols-[minmax(0,1fr)]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            {emailed ? <Mail className="h-5 w-5 text-[#0F6383]" /> : <MailWarning className="h-5 w-5 text-[#B45309]" />}
            {emailed
              ? invite
                ? `Invite sent to ${first}`
                : `Reset link sent to ${first}`
              : "The email didn't go out"}
          </DialogTitle>
          <DialogDescription>
            {emailed ? (
              <>
                {invite ? 'An invite' : 'A link to choose a new password'} is on its way to{' '}
                <strong className="text-foreground">{user.email}</strong>. It works once
                {invite ? ', for 24 hours' : ', for one hour'}.
              </>
            ) : (
              <>
                {problem ?? 'The email service had a problem'}. Copy the link below and send it to {first} another way —
                a message, or your own email.
              </>
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="min-w-0 space-y-2">
          <p className="text-sm text-muted-foreground">
            {emailed ? 'You can also copy the link, if they can’t find the email:' : 'Their link:'}
          </p>
          <div className="flex min-w-0 items-center gap-2 rounded-xl bg-[#F3F7F8] p-3">
            <code className="min-w-0 flex-1 truncate font-mono text-sm select-all" data-testid="invite-link" title={link}>
              {link}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await navigator.clipboard.writeText(link)
                setCopied(true)
              }}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? 'Copied' : 'Copy link'}
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">Anyone with this link can set the password — send it only to {first}.</p>
        </div>
        <DialogFooter>
          <Button onClick={close}>Done</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeactivateDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  // Someone who never joined has no history: remove them outright. Anyone
  // who has used SafeHaven is only ever deactivated (the record keeps them).
  const neverJoined = !!user && user.must_change_password && !user.last_login_at
  const action = useMutation({
    mutationFn: (id: string) => (neverJoined ? removeInvite(id) : updateUser(id, { is_active: false }).then(() => undefined)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      onClose()
    },
  })
  if (!user) return null
  const first = user.full_name.split(' ')[0]

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{neverJoined ? `Remove ${first}'s invite?` : `Deactivate ${user.full_name}?`}</DialogTitle>
          <DialogDescription>
            {neverJoined
              ? `${first} never signed in, so the account is deleted completely and the invite link stops working. You can invite them again any time.`
              : "They are signed out straight away and can't sign in again. Their past actions stay in the records. You can reactivate them later."}
          </DialogDescription>
        </DialogHeader>
        {action.isError && (
          <p className="text-sm text-destructive">
            {action.error instanceof Error ? action.error.message : 'Could not do that'}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => action.mutate(user.id)} disabled={action.isPending}>
            {neverJoined ? 'Remove invite' : 'Deactivate'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
