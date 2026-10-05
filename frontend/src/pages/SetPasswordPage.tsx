import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { getPasswordLink, setPasswordFromLink } from '@/api/auth'
import { AuthScreen, authButton, authField } from '@/components/AuthScreen'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth-context'

const schema = z
  .object({
    new_password: z.string().min(10, 'At least 10 characters'),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: "The two passwords don't match" })

type Values = z.infer<typeof schema>

/** The token rides in the URL fragment (#token=…), which browsers never send to a server. */
function tokenFromUrl(): string {
  return new URLSearchParams(window.location.hash.slice(1)).get('token') ?? ''
}

/**
 * Where an invite or reset email lands: choose a password, then straight
 * into the dashboard (a new user's guided tour starts there).
 */
export function SetPasswordPage() {
  const [token] = useState(tokenFromUrl)
  const { signInWithToken, logout } = useAuth()
  const navigate = useNavigate()
  const [serverError, setServerError] = useState<string | null>(null)
  const link = useQuery({
    queryKey: ['password-link', token],
    queryFn: () => getPasswordLink(token),
    enabled: token !== '',
    retry: false,
  })
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(schema) })

  async function onSubmit(values: Values) {
    setServerError(null)
    try {
      const { access_token } = await setPasswordFromLink(token, values.new_password)
      // Whoever was signed in on this browser before is not who this link is for.
      logout()
      await signInWithToken(access_token)
      // Drop the spent token from the address bar and history.
      navigate('/patients', { replace: true })
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : 'Could not save the password. Please try again.')
    }
  }

  if (!token || link.isError) {
    return (
      <AuthScreen>
        <div className="flex flex-col gap-2">
          <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">This link doesn't work</h2>
          <p className="text-base text-[#4A5558]">
            {link.error instanceof ApiError
              ? link.error.message
              : 'It may be incomplete. Open it again from the email, or ask your admin for a new one.'}
          </p>
        </div>
        <Link to="/forgot-password" className={`${authButton} flex items-center justify-center`}>
          Send me a new link
        </Link>
        <Link to="/login" className="self-center text-sm font-medium text-[#0F6383] underline-offset-4 hover:underline py-2">
          Back to sign in
        </Link>
      </AuthScreen>
    )
  }

  if (link.isLoading || !link.data) {
    return (
      <AuthScreen>
        <p className="py-8 text-center text-[#4A5558]">Checking your link…</p>
      </AuthScreen>
    )
  }

  const invite = link.data.purpose === 'invite'
  return (
    <AuthScreen onSubmit={handleSubmit(onSubmit)}>
      <div className="flex flex-col gap-2">
        <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">
          {invite ? `Welcome, ${link.data.full_name.split(' ')[0]}` : 'Choose a new password'}
        </h2>
        <p className="text-base text-[#4A5558]">
          {invite ? 'Choose a password to finish setting up your account.' : 'Your old password stops working once you save.'}
        </p>
      </div>

      {serverError && (
        <Alert variant="destructive">
          <AlertDescription>{serverError}</AlertDescription>
        </Alert>
      )}

      {/* Lets password managers save the new password against the right account. */}
      <input type="email" autoComplete="username" value={link.data.email} readOnly hidden />
      <div className="flex flex-col gap-2">
        <span className="text-[15px] font-medium">Email</span>
        <span className="text-base text-[#2E3A3D]">{link.data.email}</span>
      </div>

      <div className="flex flex-col gap-2">
        <label htmlFor="new_password" className="text-[15px] font-medium">
          Password
        </label>
        <input
          id="new_password"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.new_password}
          aria-describedby="new_password-hint"
          className={authField}
          {...register('new_password')}
        />
        {errors.new_password ? (
          <p className="text-sm text-red-700">{errors.new_password.message}</p>
        ) : (
          <p id="new_password-hint" className="text-sm text-[#5B676A]">
            At least 10 characters. A short sentence is easy to remember.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor="confirm" className="text-[15px] font-medium">
          Password again
        </label>
        <input
          id="confirm"
          type="password"
          autoComplete="new-password"
          aria-invalid={!!errors.confirm}
          className={authField}
          {...register('confirm')}
        />
        {errors.confirm && <p className="text-sm text-red-700">{errors.confirm.message}</p>}
      </div>

      <button type="submit" disabled={isSubmitting} className={authButton} data-testid="set-password-submit">
        {isSubmitting ? 'Saving…' : invite ? 'Save and sign in' : 'Save new password'}
      </button>
    </AuthScreen>
  )
}
