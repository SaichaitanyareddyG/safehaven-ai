import { useMutation } from '@tanstack/react-query'
import { PauseCircle, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { deactivateMyAccount, deleteMyAccount } from '@/api/patient-app'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { MyCard } from '@/features/patient-app/MyAppLayout'
import { turnOffReminders } from '@/features/patient-app/reminders'
import { ApiError } from '@/lib/api-client'
import { clearPatientToken } from '@/lib/auth-storage'
import { queryClient } from '@/lib/query-client'

type Action = 'deactivate' | 'delete'

const TEXT: Record<Action, { title: string; body: string; button: string; done: string }> = {
  deactivate: {
    title: 'Deactivate your account?',
    body:
      'You will be signed out and your reminders will stop. Your account is kept: sign in again with the same ' +
      'email and password whenever you want it back.',
    button: 'Deactivate',
    done: 'Your account is deactivated. Sign in again any time to switch it back on.',
  },
  delete: {
    title: 'Delete your account?',
    body:
      'Your sign-in, password and calendar reminders are removed for good. Your hospital keeps its record of your ' +
      'care. To use the app again later, ask your care team for a new invite.',
    button: 'Delete for good',
    done: 'Your account is deleted.',
  },
}

/** The patient's (or caregiver's) own account: pause it or remove it. Each
 *  needs the password, so someone else holding the phone cannot. */
export function MyAccountCard() {
  const [action, setAction] = useState<Action | null>(null)
  return (
    <MyCard className="flex flex-col gap-2" data-testid="my-account">
      <p className="text-lg font-semibold">Your account</p>
      <button
        type="button"
        onClick={() => setAction('deactivate')}
        className="flex min-h-11 items-center gap-2 self-start text-base font-semibold text-[#0F6383]"
        data-testid="my-account-deactivate"
      >
        <PauseCircle className="h-5 w-5" aria-hidden="true" />
        Deactivate my account
      </button>
      <button
        type="button"
        onClick={() => setAction('delete')}
        className="flex min-h-11 items-center gap-2 self-start text-base font-semibold text-[#9B1C12]"
        data-testid="my-account-delete"
      >
        <Trash2 className="h-5 w-5" aria-hidden="true" />
        Delete my account
      </button>
      {action && <ConfirmDialog action={action} onClose={() => setAction(null)} />}
    </MyCard>
  )
}

function ConfirmDialog({ action, onClose }: { action: Action; onClose: () => void }) {
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const text = TEXT[action]
  const run = useMutation({
    mutationFn: () => (action === 'delete' ? deleteMyAccount(password) : deactivateMyAccount(password)),
    onSuccess: async () => {
      await turnOffReminders().catch(() => undefined)
      clearPatientToken()
      queryClient.removeQueries({ queryKey: ['my'] })
      navigate('/my/sign-in', { replace: true, state: { notice: text.done } })
    },
  })
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-md" data-testid="my-account-confirm">
        <DialogHeader>
          <DialogTitle className="text-2xl">{text.title}</DialogTitle>
          <DialogDescription className="text-base leading-relaxed">{text.body}</DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (password && !run.isPending) run.mutate()
          }}
        >
          <label htmlFor="my-account-password" className="text-base font-medium">
            Type your password to confirm
          </label>
          <input
            id="my-account-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="h-14 w-full rounded-xl border-[1.5px] border-[#C9D6DB] bg-white px-4 text-lg outline-none focus:border-[#0F6383]"
            data-testid="my-account-password"
          />
          {run.isError && (
            <p className="text-base text-red-700" role="alert">
              {run.error instanceof ApiError ? run.error.message : 'Something went wrong. Please try again.'}
            </p>
          )}
          <DialogFooter className="flex-col gap-2 sm:flex-col">
            <button
              type="submit"
              disabled={!password || run.isPending}
              className={
                'flex min-h-12 w-full items-center justify-center rounded-xl text-lg font-semibold text-white disabled:opacity-50 ' +
                (action === 'delete' ? 'bg-[#9B1C12]' : 'bg-[#0F6383]')
              }
              data-testid="my-account-confirm-button"
            >
              {run.isPending ? 'Please wait…' : text.button}
            </button>
            <button type="button" onClick={onClose} className="min-h-11 w-full text-base font-semibold text-[#53656E]">
              Cancel
            </button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
