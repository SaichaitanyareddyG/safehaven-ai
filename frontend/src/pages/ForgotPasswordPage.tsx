import { MailCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { forgotPassword } from '@/api/auth'
import { AuthScreen, authButton, authField } from '@/components/AuthScreen'
import { ApiError } from '@/lib/api-client'

/** Ask for a reset link by email. Same answer whether or not the account exists. */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const valid = /^\S+@\S+\.\S+$/.test(email.trim())

  if (sentTo) {
    return (
      <AuthScreen>
        <MailCheck className="h-10 w-10 text-[#0E7C72]" aria-hidden="true" />
        <div className="flex flex-col gap-2">
          <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">Check your email</h2>
          <p className="text-base leading-relaxed text-[#4A5558]">
            If <strong className="text-[#0B0D0E]">{sentTo}</strong> has a SafeHaven account, a link to choose a new
            password is on its way. It works once, for one hour. Nothing there? Check spam, or ask your ward
            administrator.
          </p>
        </div>
        <Link to="/login" className={`${authButton} flex items-center justify-center`}>
          Back to sign in
        </Link>
      </AuthScreen>
    )
  }

  return (
    <AuthScreen
      onSubmit={async (e) => {
        e.preventDefault()
        if (!valid) return
        setSending(true)
        setError(null)
        try {
          await forgotPassword(email.trim())
          setSentTo(email.trim())
        } catch (err) {
          setError(err instanceof ApiError && err.status === 429 ? 'Too many tries — wait a minute.' : 'Could not send the link. Please try again.')
        } finally {
          setSending(false)
        }
      }}
    >
      <div className="flex flex-col gap-2">
        <h2 className="text-[26px] font-semibold tracking-tight sm:text-[32px]">Forgot your password?</h2>
        <p className="text-base text-[#4A5558]">We'll email you a link to choose a new one.</p>
      </div>
      <div className="flex flex-col gap-2">
        <label htmlFor="email" className="text-[15px] font-medium">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="username"
          placeholder="name@hospital.org"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={authField}
        />
        {error && <p className="text-sm text-red-700">{error}</p>}
      </div>
      <button type="submit" disabled={!valid || sending} className={authButton} data-testid="forgot-submit">
        {sending ? 'Sending…' : 'Email me a link'}
      </button>
      <Link to="/login" className="self-center text-sm font-medium text-[#0E7C72] underline-offset-4 hover:underline">
        Back to sign in
      </Link>
    </AuthScreen>
  )
}
