import { zodResolver } from '@hookform/resolvers/zod'
import { Bell, Eye, EyeOff, Lock, MessageSquare, Pill } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { z } from 'zod'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { ApiError } from '@/lib/api-client'
import { useAuth } from '@/lib/auth-context'

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

type LoginFormValues = z.infer<typeof loginSchema>

/**
 * Sign-in, in the SafeHaven brand shared with the wrist band: a dark teal
 * panel with the band's "beacon" rings, and one big card. Design option A of
 * the "SafeHaven Login" canvas. On a phone the panel becomes a header and the
 * card overlaps it.
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

  if (user) {
    const redirectTo = (location.state as { from?: string } | null)?.from ?? '/patients'
    return <Navigate to={redirectTo} replace />
  }

  async function onSubmit(values: LoginFormValues) {
    setServerError(null)
    try {
      await login(values.email, values.password)
      navigate('/patients', { replace: true })
    } catch (error) {
      setServerError(error instanceof ApiError ? error.message : 'Unable to sign in. Please try again.')
    }
  }

  const field =
    'h-[52px] w-full rounded-xl border-[1.5px] border-[#CBD4D3] bg-white px-4 text-base text-[#0B0D0E] outline-none ' +
    'placeholder:text-[#7A8588] focus-visible:border-[#0E7C72] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/30 ' +
    'aria-invalid:border-red-600'

  return (
    <div className="flex min-h-screen flex-col bg-[#F4F7F6] lg:flex-row">
      {/* Brand panel */}
      <section className="relative flex flex-col gap-5 overflow-hidden bg-[#0A2422] px-6 pt-7 pb-16 text-[#F2F4F3] lg:min-h-screen lg:flex-1 lg:gap-10 lg:px-16 lg:py-14">
        <BeaconRings />
        <div className="relative flex items-center gap-3">
          <Logo />
          <span className="text-base font-semibold tracking-[0.25em] text-[#7FE0D6] lg:text-xl">SAFEHAVEN AI</span>
        </div>
        <div className="relative flex max-w-xl flex-col gap-5 lg:mt-auto">
          <h1 className="text-3xl leading-tight font-semibold tracking-tight lg:text-[52px] lg:leading-[1.08]">
            Calm, watchful care for every bed.
          </h1>
          <p className="hidden text-lg leading-relaxed text-[#B8C3C1] lg:block">
            Fall alerts from the wrist band, medication checks at the bedside, and care plans patients understand —
            in one place for the ward.
          </p>
        </div>
        <ul className="relative hidden max-w-xl flex-col gap-3.5 lg:flex">
          <Feature icon={<Bell className="h-5 w-5" />} text="Fall and help alerts in seconds" />
          <Feature icon={<Pill className="h-5 w-5" />} text="Right medicine, right patient, every time" />
          <Feature icon={<MessageSquare className="h-5 w-5" />} text="Care plans explained in the patient's words" />
        </ul>
      </section>

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
            <label htmlFor="password" className="text-[15px] font-medium">
              Password
            </label>
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
                className="absolute top-1 right-1 flex h-11 w-11 items-center justify-center rounded-lg text-[#4A5558] hover:bg-[#EEF3F2] focus-visible:ring-3 focus-visible:ring-[#2EC4B6]/40 focus-visible:outline-none"
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
            className="mt-1 h-[54px] rounded-xl bg-[#2EC4B6] text-[17px] font-semibold text-[#062320] transition-colors hover:bg-[#27B0A3] focus-visible:ring-3 focus-visible:ring-[#0E7C72]/50 focus-visible:outline-none disabled:opacity-60"
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

function Feature({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <li className="flex items-center gap-3.5 text-base text-[#DCE4E2]">
      <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-[#0F3B37] text-[#7FE0D6]" aria-hidden="true">
        {icon}
      </span>
      {text}
    </li>
  )
}

function Logo() {
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true" className="h-7 w-7 lg:h-[34px] lg:w-[34px]">
      <circle cx="17" cy="17" r="15" fill="none" stroke="#2EC4B6" strokeWidth="2.5" />
      <path
        d="M7 18 L12 18 L14.5 12 L18.5 23 L21 16 L27 16"
        fill="none"
        stroke="#2EC4B6"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** The band's fall-alert "beacon", as quiet concentric rings. */
function BeaconRings() {
  return (
    <svg
      viewBox="0 0 760 760"
      aria-hidden="true"
      className="pointer-events-none absolute -top-40 -right-44 h-[420px] w-[420px] lg:top-auto lg:-right-64 lg:-bottom-64 lg:h-[760px] lg:w-[760px]"
    >
      <circle cx="380" cy="380" r="120" fill="none" stroke="#2EC4B6" strokeOpacity="0.35" strokeWidth="2" />
      <circle cx="380" cy="380" r="200" fill="none" stroke="#2EC4B6" strokeOpacity="0.22" strokeWidth="2" />
      <circle cx="380" cy="380" r="280" fill="none" stroke="#2EC4B6" strokeOpacity="0.14" strokeWidth="2" />
      <circle cx="380" cy="380" r="360" fill="none" stroke="#2EC4B6" strokeOpacity="0.08" strokeWidth="2" />
      <circle cx="380" cy="380" r="60" fill="#2EC4B6" fillOpacity="0.18" />
    </svg>
  )
}
