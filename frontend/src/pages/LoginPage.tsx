import { zodResolver } from '@hookform/resolvers/zod'
import { Eye, EyeOff, Lock } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { BrandPanel } from '@/components/BrandPanel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth-context'

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

type LoginFormValues = z.infer<typeof loginSchema>

/**
 * Sign-in, in the SafeHaven brand shared with the wrist band: the dark teal
 * BrandPanel and one big card. Design option A of the "SafeHaven Login"
 * canvas. On a phone the panel becomes a header and the card overlaps it.
 *
 * No self sign-up here on purpose: clinical accounts are created by an
 * administrator.
 */
export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [serverError, setServerError] = useState<string | null>(null)
  const [showPassword, setShowPassword] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) })

  const redirectTo = (location.state as { from?: string } | null)?.from ?? '/patients'
  if (user) {
    return <Navigate to={redirectTo} replace />
  }

  async function onSubmit(values: LoginFormValues) {
    setServerError(null)
    try {
      await login(values.email, values.password)
      navigate(redirectTo, { replace: true })
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : 'Unable to sign in. Please try again.')
    }
  }

  const field =
    'h-[52px] w-full rounded-xl border-[1.5px] border-[#CBD4D3] bg-white px-4 text-base text-[#0B0D0E] outline-none ' +
    'placeholder:text-[#7A8588] focus-visible:border-[#0F6383] focus-visible:ring-3 focus-visible:ring-[#4F93AD]/30 ' +
    'aria-invalid:border-red-600'

  return (
    <div className="flex min-h-screen flex-col bg-[#F3F7F8] lg:flex-row">
      <BrandPanel />

      {/* Sign-in card */}
      <main className="relative -mt-10 flex flex-1 justify-center px-4 pb-8 lg:mt-0 lg:items-center lg:px-6 lg:py-12">
        <form
          className="flex w-full max-w-[480px] flex-col gap-5 self-start rounded-[20px] bg-white p-6 text-[#0B0D0E] shadow-[0_1px_2px_rgba(11,13,14,0.06),0_12px_40px_rgba(11,13,14,0.10)] sm:p-12 lg:self-center"
          onSubmit={handleSubmit(onSubmit)}
          noValidate
        >
          <div className="flex flex-col gap-2">
            <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">Welcome back</h2>
            <p className="text-base text-[#4A5558]">Sign in to your ward dashboard</p>
          </div>

          {serverError && (
            <Alert variant="destructive">
              <AlertDescription>{serverError}</AlertDescription>
            </Alert>
          )}

          <div className="flex flex-col gap-2">
            <label htmlFor="email" className="text-[15px] font-medium">
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              placeholder="name@hospital.org"
              aria-invalid={!!errors.email}
              className={field}
              {...register('email')}
            />
            {errors.email && <p className="text-sm text-red-700">{errors.email.message}</p>}
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-3">
              <label htmlFor="password" className="text-[15px] font-medium">
                Password
              </label>
              <Link
                to="/forgot-password"
                className="rounded text-sm font-medium text-[#0F6383] underline-offset-4 hover:underline focus-visible:ring-3 focus-visible:ring-[#4F93AD]/40 focus-visible:outline-none"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                aria-invalid={!!errors.password}
                className={`${field} pr-14`}
                {...register('password')}
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-pressed={showPassword}
                className="absolute top-1 right-1 flex h-11 w-11 items-center justify-center rounded-lg text-[#4A5558] hover:bg-[#EEF3F2] focus-visible:ring-3 focus-visible:ring-[#4F93AD]/40 focus-visible:outline-none"
              >
                {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
              </button>
            </div>
            {errors.password && <p className="text-sm text-red-700">{errors.password.message}</p>}
          </div>

          <button
            type="submit"
            disabled={isSubmitting}
            data-testid="login-submit"
            className="mt-1 h-[54px] rounded-xl bg-[#0F6383] text-[17px] font-semibold text-white transition-colors hover:bg-[#0C5571] focus-visible:ring-3 focus-visible:ring-[#0F6383]/40 focus-visible:outline-none disabled:opacity-60"
          >
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </button>

          <p className="text-center text-sm text-[#4A5558]">No account yet? Ask your ward administrator.</p>

          <div className="flex items-center justify-center gap-2 border-t border-[#E3E9E8] pt-4 text-[13px] text-[#5B676A]">
            <Lock className="h-4 w-4" aria-hidden="true" />
            Authorised clinical staff · demo data only
          </div>
        </form>
      </main>
    </div>
  )
}
