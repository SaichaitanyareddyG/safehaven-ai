import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Check, Copy, KeyRound, Search, UserPlus } from 'lucide-react'
import { useState } from 'react'

import { createUser, listUsers, resetUserPassword, updateUser } from '@/api/admin-users'
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
import type { AdminUser, OneTimePasswordResponse, Role } from '@/types/auth'

const USERS_QUERY_KEY = ['admin-users']

/**
 * Admin only: who can sign in to this dashboard. New accounts get a one-time
 * password, shown once, which the admin hands over in person; its owner
 * chooses their own at first sign-in. Accounts are switched off, never
 * deleted, so the audit trail keeps a real person behind every action.
 */
export function UsersPage() {
  const { user: me } = useAuth()
  const [search, setSearch] = useState('')
  const [issued, setIssued] = useState<{ response: OneTimePasswordResponse; reason: 'created' | 'reset' } | null>(null)
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
                      onPasswordIssued={(response) => setIssued({ response, reason: 'reset' })}
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

      <OneTimePasswordDialog issued={issued} onClose={() => setIssued(null)} />
      <DeactivateDialog user={confirming} onClose={() => setConfirming(null)} />
    </AppLayout>
  )
}

function UserRow({
  user,
  isMe,
  onPasswordIssued,
  onDeactivate,
}: {
  user: AdminUser
  isMe: boolean
  onPasswordIssued: (r: OneTimePasswordResponse) => void
  onDeactivate: () => void
}) {
  const queryClient = useQueryClient()
  const refresh = () => queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })

  const changeRole = useMutation({ mutationFn: (role: Role) => updateUser(user.id, { role }), onSuccess: refresh })
  const reactivate = useMutation({ mutationFn: () => updateUser(user.id, { is_active: true }), onSuccess: refresh })
  const reset = useMutation({ mutationFn: () => resetUserPassword(user.id), onSuccess: onPasswordIssued })

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
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
              aria-label={`Reset password for ${user.full_name}`}
              title="Reset password"
            >
              <KeyRound className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={onDeactivate}
              className="border-red-200 text-red-700 hover:bg-red-50 hover:text-red-800"
            >
              Deactivate
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
        muted ? 'bg-muted text-muted-foreground' : role === 'admin' ? 'bg-[#0A2422] text-[#7FE0D6]' : 'bg-[#E3F4F1] text-[#0A5C55]',
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
      : ['bg-[#0E7C72]', 'text-[#0A5C55]', 'Active']
  return (
    <span className={cn('inline-flex items-center gap-1.5', text)}>
      <span className={cn('h-2 w-2 rounded-full', dot)} aria-hidden="true" />
      {label}
    </span>
  )
}

function AddUserForm({ onCreated }: { onCreated: (r: OneTimePasswordResponse) => void }) {
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
        <UserPlus className="h-5 w-5 text-[#0E7C72]" />
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
        {create.isPending ? 'Creating…' : 'Create user'}
      </Button>
      <p className="text-sm leading-relaxed text-muted-foreground">
        SafeHaven shows a one-time password once. Give it to them in person — they choose their own at first sign-in.
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
        checked ? 'border-[#0E7C72] bg-[#F1FAF8]' : 'border-input',
      )}
    >
      <input
        type="radio"
        name="new-user-role"
        value={value}
        checked={checked}
        onChange={() => onChange(value)}
        className="mt-0.5 h-4.5 w-4.5 accent-[#0E7C72]"
      />
      <span className="flex flex-col">
        <span className="font-medium">{title}</span>
        <span className="text-sm text-muted-foreground">{text}</span>
      </span>
    </label>
  )
}

function OneTimePasswordDialog({
  issued,
  onClose,
}: {
  issued: { response: OneTimePasswordResponse; reason: 'created' | 'reset' } | null
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  if (!issued) return null
  const { user, one_time_password: password } = issued.response

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false)
          onClose()
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{issued.reason === 'created' ? `${user.full_name} can now sign in` : 'New one-time password'}</DialogTitle>
          <DialogDescription>
            Give this to {user.full_name.split(' ')[0]} in person. It is shown only now, and works once: they choose their
            own password when they sign in.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="text-sm">
            <span className="text-muted-foreground">Email: </span>
            <span className="font-medium">{user.email}</span>
          </div>
          <div className="flex items-center gap-2 rounded-xl bg-[#F4F7F6] p-3">
            <code className="flex-1 font-mono text-xl tracking-wider select-all" data-testid="one-time-password">
              {password}
            </code>
            <Button
              variant="outline"
              size="sm"
              onClick={async () => {
                await navigator.clipboard.writeText(password)
                setCopied(true)
              }}
            >
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={() => {
              setCopied(false)
              onClose()
            }}
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function DeactivateDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const queryClient = useQueryClient()
  const deactivate = useMutation({
    mutationFn: (id: string) => updateUser(id, { is_active: false }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
      onClose()
    },
  })
  if (!user) return null

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Deactivate {user.full_name}?</DialogTitle>
          <DialogDescription>
            They are signed out straight away and can't sign in again. Their past actions stay in the records. You can
            reactivate them later.
          </DialogDescription>
        </DialogHeader>
        {deactivate.isError && (
          <p className="text-sm text-destructive">
            {deactivate.error instanceof Error ? deactivate.error.message : 'Could not deactivate'}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => deactivate.mutate(user.id)} disabled={deactivate.isPending}>
            Deactivate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
