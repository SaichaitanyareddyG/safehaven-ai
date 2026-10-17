import { Loader2, MailCheck } from 'lucide-react'
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { exchangeSignInLink, requestSignInLink } from '@/api/patient-app'
import { Logo } from '@/components/BrandPanel'
import { usePatientAppHead } from '@/features/patient-app/use-my-data'
import { ApiError } from '@/lib/api-client'
import { getPatientToken, setPatientToken } from '@/lib/auth-storage'

const field =
  'h-14 w-full rounded-xl border-[1.5px] border-[#C9D6DB] bg-white px-4 text-lg outline-none focus:border-[#0F6383] focus:ring-[3px] focus:ring-[#4F93AD]/40'
const button =
  'flex h-14 w-full items-center justify-center gap-2 rounded-xl bg-[#0F6383] text-lg font-semibold text-white hover:bg-[#0B5068] disabled:opacity-50'

/** Patient sign-in, no password: open the emailed link (which lands here with
 *  #token=...), or type your email to get a fresh link. */
export function MySignInPage() {
  const navigate = useNavigate()
  usePatientAppHead()
  const [linkToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token'))
  const [exchanging, setExchanging] = useState(!!linkToken)
  const exchanged = useRef(false)
  const [linkProblem, setLinkProblem] = useState<string | null>(null)

  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const valid = /^\S+@\S+\.\S+$/.test(email.trim())

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
    const token = linkToken
    if (!token) {
      if (getPatientToken()) navigate('/my', { replace: true })
      return
    }
    // The link works once: StrictMode's second effect run must not spend it again.
    if (exchanged.current) return
    exchanged.current = true
    // Out of the address bar and the browser history straight away.
    window.history.replaceState(null, '', window.location.pathname)
    exchangeSignInLink(token)
      .then((session) => {
        setPatientToken(session.access_token)
        navigate('/my', { replace: true })
      })
      .catch((err) => {
        setExchanging(false)
        setLinkProblem(
          err instanceof ApiError && err.status === 410
            ? 'This sign-in link has expired or was already used. Enter your email below and we will send a new one.'
            : "We couldn't sign you in just now. Check your connection, or ask for a new link below.",
        )
      })
  }, [linkToken, navigate])

  if (exchanging) {
    return (
      <Shell>
        <div className="flex flex-col items-center gap-4 py-6 text-center">
          <Loader2 className="h-10 w-10 animate-spin text-[#0F6383]" aria-hidden="true" />
          <p className="text-xl">Signing you in…</p>
        </div>
      </Shell>
    )
  }

  if (sentTo) {
    return (
      <Shell>
        <MailCheck className="h-12 w-12 text-[#0F6383]" aria-hidden="true" />
        <h2 className="text-[28px] font-semibold tracking-tight">Check your email</h2>
        <p className="text-lg leading-relaxed text-[#2E3A3D]">
          If <strong>{sentTo}</strong> can use SafeHaven, a sign-in link is on its way. It works once, for 15 minutes.
          Open it on this phone.
        </p>
        <p className="text-base text-[#53656E]">Nothing there? Check your spam folder, or ask your nurse.</p>
        <button type="button" className="self-start py-2 text-base font-medium text-[#0F6383]" onClick={() => setSentTo(null)}>
          Use a different email
        </button>
      </Shell>
    )
  }

  return (
    <Shell>
      <h2 className="text-[28px] font-semibold tracking-tight">Sign in</h2>
      <p className="text-lg leading-relaxed text-[#2E3A3D]">
        Your medicines, hospital visits and care instructions, explained in plain words. No password needed — we email
        you a link.
      </p>
      {linkProblem && (
        <p className="rounded-xl bg-[#FFF4E5] p-4 text-base text-[#7A4200]" role="alert">
          {linkProblem}
        </p>
      )}
      <form
        className="flex flex-col gap-4"
        noValidate
        onSubmit={async (e) => {
          e.preventDefault()
          if (!valid) return
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
        <div className="flex flex-col gap-2">
          <label htmlFor="my-email" className="text-base font-medium">
            Your email
          </label>
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
          {error && <p className="text-base text-red-700">{error}</p>}
        </div>
        <button type="submit" disabled={!valid || sending} className={button} data-testid="my-request-link">
          {sending ? 'Sending…' : 'Email me a sign-in link'}
        </button>
      </form>
      <p className="text-sm leading-relaxed text-[#53656E]">
        Use the email address you gave the hospital. For your privacy, our emails never include medical details.
      </p>
    </Shell>
  )
}

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
