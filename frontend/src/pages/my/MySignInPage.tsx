import { useQuery } from '@tanstack/react-query'
import { Eye, EyeOff, Loader2, MailCheck } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { getLinkInfo, requestSignInLink, setMyPassword, signInWithPassword } from '@/api/patient-app'
import { Logo } from '@/components/BrandPanel'
import { usePatientAppHead } from '@/features/patient-app/use-my-data'
import { ApiError } from '@/lib/api-client'
import { getPatientToken, setPatientToken } from '@/lib/auth-storage'
import { cn } from '@/lib/utils'

const field =
  'h-14 w-full rounded-xl border-[1.5px] border-[#C9D6DB] bg-white px-4 text-lg outline-none focus:border-[#0F6383] focus:ring-[3px] focus:ring-[#4F93AD]/40'
const button =
  'flex h-14 w-full items-center justify-center gap-2 rounded-xl bg-[#0F6383] text-lg font-semibold text-white hover:bg-[#0B5068] disabled:opacity-50'

/** Patient sign-in: email + password. The invite or "Forgot password" email
 *  lands here with #token=... to create or reset the password first. */
export function MySignInPage() {
  const navigate = useNavigate()
  usePatientAppHead()
  const [linkToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token'))

  // A link opened in a tab already on this page changes only the #fragment,
  // which does not reload the page: start over so it is read.
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash.includes('token=')) window.location.reload()
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    if (!linkToken && getPatientToken()) navigate('/my', { replace: true })
    // Out of the address bar and the browser history straight away; kept in state.
    if (linkToken) window.history.replaceState(null, '', window.location.pathname)
  }, [linkToken, navigate])

  const [mode, setMode] = useState<'sign-in' | 'forgot'>('sign-in')
  const [linkGone, setLinkGone] = useState(false)

  if (linkToken && !linkGone) {
    return <ChoosePassword token={linkToken} onGone={() => setLinkGone(true)} />
  }
  return mode === 'forgot' ? (
    <ForgotPassword onBack={() => setMode('sign-in')} />
  ) : (
    <SignIn
      notice={linkGone ? 'This link was already used or has expired. Sign in below, or use "Forgot password?".' : null}
      onForgot={() => setMode('forgot')}
    />
  )
}

function SignIn({ notice, onForgot }: { notice: string | null; onForgot: () => void }) {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const valid = /^\S+@\S+\.\S+$/.test(email.trim()) && password.length > 0

  return (
    <Shell>
      <h2 className="text-[28px] font-semibold tracking-tight">Sign in</h2>
      <p className="text-lg leading-relaxed text-[#2E3A3D]">
        Your medicines, hospital visits and care instructions, explained in plain words.
      </p>
      {notice && (
        <p className="rounded-xl bg-[#FFF4E5] p-4 text-base text-[#7A4200]" role="alert">
          {notice}
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault()
          if (!valid || busy) return
          setBusy(true)
          setError(null)
          try {
            const session = await signInWithPassword(email.trim(), password)
            setPatientToken(session.access_token)
            navigate('/my', { replace: true })
          } catch (err) {
            setError(
              err instanceof ApiError && err.status === 429
                ? 'Too many tries — please wait a minute.'
                : err instanceof ApiError && err.status === 401
                  ? err.message
                  : 'Could not sign in just now. Check your connection and try again.',
            )
          } finally {
            setBusy(false)
          }
        }}
      >
        <Field label="Your email" id="my-email">
          <input
            id="my-email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="name@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={field}
            data-testid="my-email"
          />
        </Field>
        <Field label="Password" id="my-password">
          <PasswordInput id="my-password" value={password} onChange={setPassword} autoComplete="current-password" />
        </Field>
        {error && (
          <p className="text-base text-red-700" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={!valid || busy} className={button} data-testid="my-sign-in">
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <button type="button" onClick={onForgot} className="self-start py-2 text-base font-semibold text-[#0F6383]">
        Forgot password?
      </button>
      <p className="text-sm leading-relaxed text-[#53656E]">
        First time? Open the email from your hospital and create your password there.
      </p>
    </Shell>
  )
}

function ChoosePassword({ token, onGone }: { token: string; onGone: () => void }) {
  const navigate = useNavigate()
  const info = useQuery({
    queryKey: ['my-link', token],
    queryFn: () => getLinkInfo(token),
    retry: false,
    staleTime: Infinity,
  })
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (info.error instanceof ApiError && info.error.status === 410) onGone()
  }, [info.error, onGone])

  if (info.isLoading) {
    return (
      <Shell>
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <Loader2 className="h-10 w-10 animate-spin text-[#0F6383]" aria-hidden="true" />
          <p className="text-xl">Opening your link…</p>
        </div>
      </Shell>
    )
  }
  if (info.isError) {
    return (
      <Shell>
        <p className="text-lg">We couldn't open this link just now. Check your connection and open it again.</p>
      </Shell>
    )
  }
  const firstTime = info.data?.first_time ?? true
  const tooShort = password.length > 0 && password.length < PASSWORD_MIN
  const mismatch = again.length > 0 && again !== password
  const valid = password.length >= PASSWORD_MIN && again === password

  return (
    <Shell>
      <h2 className="text-[28px] font-semibold tracking-tight">{firstTime ? 'Create your password' : 'Choose a new password'}</h2>
      {info.data?.email && (
        <p className="text-lg leading-relaxed text-[#2E3A3D]">
          For <strong>{info.data.email}</strong>. You'll sign in with this email and password.
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault()
          if (!valid || busy) return
          setBusy(true)
          setError(null)
          try {
            const session = await setMyPassword(token, password)
            setPatientToken(session.access_token)
            navigate('/my', { replace: true })
          } catch (err) {
            if (err instanceof ApiError && err.status === 410) onGone()
            else setError(err instanceof ApiError ? err.message : 'Could not save your password. Please try again.')
          } finally {
            setBusy(false)
          }
        }}
      >
        <Field label="Password" id="my-new-password" hint={`At least ${PASSWORD_MIN} characters.`}>
          <PasswordInput id="my-new-password" value={password} onChange={setPassword} autoComplete="new-password" />
        </Field>
        {tooShort && <p className="text-base text-red-700">Use at least {PASSWORD_MIN} characters.</p>}
        <Field label="Type it again" id="my-new-password-again">
          <PasswordInput id="my-new-password-again" value={again} onChange={setAgain} autoComplete="new-password" />
        </Field>
        {mismatch && <p className="text-base text-red-700">The two passwords are different.</p>}
        {error && (
          <p className="text-base text-red-700" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={!valid || busy} className={button} data-testid="my-save-password">
          {busy ? 'Saving…' : firstTime ? 'Create password and sign in' : 'Save and sign in'}
        </button>
      </form>
    </Shell>
  )
}

function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const valid = /^\S+@\S+\.\S+$/.test(email.trim())

  if (sentTo) {
    return (
      <Shell>
        <MailCheck className="h-12 w-12 text-[#0F6383]" aria-hidden="true" />
        <h2 className="text-[28px] font-semibold tracking-tight">Check your email</h2>
        <p className="text-lg leading-relaxed text-[#2E3A3D]">
          If <strong>{sentTo}</strong> can use SafeHaven, a link to choose a new password is on its way. It works once,
          for 24 hours.
        </p>
        <p className="text-base text-[#53656E]">Nothing there? Check your spam folder, or ask your nurse.</p>
        <button type="button" className="self-start py-2 text-base font-semibold text-[#0F6383]" onClick={onBack}>
          Back to sign in
        </button>
      </Shell>
    )
  }
  return (
    <Shell>
      <h2 className="text-[28px] font-semibold tracking-tight">Forgot your password?</h2>
      <p className="text-lg leading-relaxed text-[#2E3A3D]">We'll email you a link to choose a new one.</p>
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault()
          if (!valid || sending) return
          setSending(true)
          setError(null)
          try {
            await requestSignInLink(email.trim())
            setSentTo(email.trim())
          } catch (err) {
            setError(
              err instanceof ApiError && err.status === 429
                ? 'Too many tries — please wait a minute.'
                : 'Could not send the link. Please try again.',
            )
          } finally {
            setSending(false)
          }
        }}
      >
        <Field label="Your email" id="my-forgot-email">
          <input
            id="my-forgot-email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="name@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={field}
            data-testid="my-forgot-email"
          />
        </Field>
        {error && <p className="text-base text-red-700">{error}</p>}
        <button type="submit" disabled={!valid || sending} className={button} data-testid="my-request-link">
          {sending ? 'Sending…' : 'Email me a link'}
        </button>
      </form>
      <button type="button" className="self-start py-2 text-base font-semibold text-[#0F6383]" onClick={onBack}>
        Back to sign in
      </button>
    </Shell>
  )
}

function Field({ label, id, hint, children }: { label: string; id: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-base font-medium">
        {label}
      </label>
      {children}
      {hint && <p className="text-sm text-[#53656E]">{hint}</p>}
    </div>
  )
}

/** With a Show / Hide switch: typing a password on a phone blind is hard. */
function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  autoComplete: string
}) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <input
        id={id}
        type={shown ? 'text' : 'password'}
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={cn(field, 'pr-24')}
        data-testid={id}
      />
      <button
        type="button"
        onClick={() => setShown(!shown)}
        className="absolute inset-y-0 right-2 my-2 flex items-center gap-1 rounded-lg px-3 text-base font-semibold text-[#0F6383]"
        aria-label={shown ? 'Hide password' : 'Show password'}
      >
        {shown ? <EyeOff className="h-5 w-5" aria-hidden="true" /> : <Eye className="h-5 w-5" aria-hidden="true" />}
        {shown ? 'Hide' : 'Show'}
      </button>
    </div>
  )
}

const PASSWORD_MIN = 8

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-[#F3F7F8] text-[#16252C]">
      <div className="bg-[#143440] px-6 pt-8 pb-20 text-[#E6F0F3]">
        <div className="mx-auto flex max-w-md items-center gap-3">
          <Logo className="h-8 w-8" />
          <span className="text-base font-semibold tracking-[0.25em] text-[#7CC3DB]">SAFEHAVEN</span>
        </div>
        <p className="mx-auto mt-6 max-w-md text-2xl font-semibold leading-snug">Your care, in your pocket.</p>
      </div>
      <main className="mx-auto -mt-12 max-w-md px-4 pb-10">
        <div className="flex flex-col gap-5 rounded-2xl bg-white p-6 shadow-[0_12px_40px_rgba(22,37,44,0.10)]">
          {children}
        </div>
      </main>
    </div>
  )
}
