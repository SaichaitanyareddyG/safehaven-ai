import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowLeft, Lock } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { z } from 'zod'

import { changePassword } from '@/api/auth'
import { BrandPanel } from '@/components/BrandPanel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth-context'

const schema = z
  .object({
    current_password: z.string().min(1, 'Required'),
    new_password: z.string().min(10, 'At least 10 characters'),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: "The two passwords don't match" })

type Values = z.infer<typeof schema>

/**
 * Choose a password. A new user lands here first, signed in with the
 * one-time password an admin gave them; anyone can also come here from their
 * menu. Same brand screen as sign-in.
 */
export function ChangePasswordPage() {
  const { user, isLoading, refreshUser, logout } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  if (isLoading) return null
  if (!user) return <Navigate to="/login" replace />
  const firstTime = user.must_change_password

  async function onSubmit(values: Values) {
    setServerError(null)
    try {
      await changePassword({ current_password: values.current_password, new_password: values.new_password })
      await refreshUser()
      toast.success('Password changed')
      navigate('/patients', { replace: true })
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : 'Could not change the password. Please try again.')
    }
  }

  const field =
    'h-[52px] w-full rounded-xl border-[1.5px] border-[#CBD4D3] bg-white px-4 text-base text-[#0B0D0E] outline-none ' +
    'focus-visible:border-[#0E7C72] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/30 aria-invalid:border-red-600'

  return (
    <div className="flex min-h-screen flex-col bg-[#F4F7F6] lg:flex-row">
      <BrandPanel />
      <main className="relative -mt-10 flex flex-1 justify-center px-4 pb-8 lg:mt-0 lg:items-center lg:px-6 lg:py-12">
        <form
          className="flex w-full max-w-[480px] flex-col gap-5 self-start rounded-[20px] bg-white p-6 text-[#0B0D0E] shadow-[0_1px_2px_rgba(11,13,14,0.06),0_12px_40px_rgba(11,13,14,0.10)] sm:p-12 lg:self-center"
          onSubmit={handleSubmit(onSubmit)}
          noValidate
        >
          {!firstTime && (
            <Link to="/patients" className="flex items-center gap-1.5 self-start text-sm font-medium text-[#0E7C72]">
              <ArrowLeft className="h-4 w-4" />
              Back to the dashboard
            </Link>
          )}
          <div className="flex flex-col gap-2">
            <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">
              {firstTime ? `Welcome, ${user.full_name.split(' ')[0]}` : 'Change your password'}
            </h2>
            <p className="text-base text-[#4A5558]">
              {firstTime
                ? 'Choose your own password to finish setting up your account.'
                : 'You stay signed in on this device.'}
            </p>
          </div>

          {serverError && (
            <Alert variant="destructive">
              <AlertDescription>{serverError}</AlertDescription>
            </Alert>
          )}

          <PasswordField
            id="current_password"
            label={firstTime ? 'One-time password' : 'Current password'}
            autoComplete="current-password"
            error={errors.current_password?.message}
            className={field}
            {...register('current_password')}
          />
          <PasswordField
            id="new_password"
            label="New password"
            hint="At least 10 characters. A short sentence is easy to remember."
            autoComplete="new-password"
            error={errors.new_password?.message}
            className={field}
            {...register('new_password')}
          />
          <PasswordField
            id="confirm"
            label="New password again"
            autoComplete="new-password"
            error={errors.confirm?.message}
            className={field}
            {...register('confirm')}
          />

          <button
            type="submit"
            disabled={isSubmitting}
            data-testid="change-password-submit"
            className="mt-1 h-[54px] rounded-xl bg-[#2EC4B6] text-[17px] font-semibold text-[#062320] transition-colors hover:bg-[#27B0A3] focus-visible:ring-3 focus-visible:ring-[#0E7C72]/50 focus-visible:outline-none disabled:opacity-60"
          >
            {isSubmitting ? 'Saving…' : firstTime ? 'Save and continue' : 'Change password'}
          </button>

          {firstTime && (
            <button
              type="button"
              onClick={() => {
                logout()
                navigate('/login')
              }}
              className="self-center text-sm font-medium text-[#4A5558] underline-offset-4 hover:underline"
            >
              Not you? Sign out
            </button>
          )}

          <div className="flex items-center justify-center gap-2 border-t border-[#E3E9E8] pt-4 text-[13px] text-[#5B676A]">
            <Lock className="h-4 w-4" aria-hidden="true" />
            Authorised clinical staff · demo data only
          </div>
        </form>
      </main>
    </div>
  )
}

type PasswordFieldProps = React.ComponentProps<'input'> & {
  id: string
  label: string
  hint?: string
  error?: string
}

function PasswordField({ id, label, hint, error, ...input }: PasswordFieldProps) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-[15px] font-medium">
        {label}
      </label>
      <input id={id} type="password" aria-invalid={!!error} aria-describedby={hint ? `${id}-hint` : undefined} {...input} />
      {hint && !error && (
        <p id={`${id}-hint`} className="text-sm text-[#5B676A]">
          {hint}
        </p>
      )}
      {error && <p className="text-sm text-red-700">{error}</p>}
    </div>
  )
}
