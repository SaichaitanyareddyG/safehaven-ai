import type { Page } from '@playwright/test'

export const API = process.env.E2E_API_URL ?? 'http://localhost:8000'

async function call(path: string, init: RequestInit & { token?: string } = {}) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (init.token) headers.Authorization = `Bearer ${init.token}`
  const response = await fetch(API + path, { ...init, headers })
  const text = await response.text()
  return { status: response.status, body: text ? JSON.parse(text) : null }
}

let staffForThisWorker: Promise<{ email: string; token: string }> | null = null

/** A nurse account, one per test worker: sign-up is rate limited (15 a
 *  minute), so tests share it. Needs ALLOW_SELF_REGISTRATION on the backend. */
export function newStaff() {
  staffForThisWorker ??= createStaff()
  return staffForThisWorker
}

async function createStaff() {
  const email = `e2e.${Date.now()}.${Math.random().toString(36).slice(2, 7)}@example.com`
  await call('/auth/register', { method: 'POST', body: JSON.stringify({ email, password: 'supersecret123', full_name: 'E2E Nurse' }) })
  const login = await call('/auth/login', { method: 'POST', body: JSON.stringify({ email, password: 'supersecret123' }) })
  return { email, token: login.body.access_token as string }
}

/** A patient invited to the app, with medication instructions approved.
 *  Email is not set up on a test backend, so the invite link comes back. */
export async function newPatientWithApp(token: string, instructions: string[] = []) {
  const stamp = Date.now()
  const created = await call('/patients', {
    method: 'POST',
    token,
    body: JSON.stringify({
      first_name: 'Maria',
      last_name: `Lopez${stamp % 1000}`,
      date_of_birth: '1948-03-02',
      reason_for_visit: 'Hip surgery',
      email: `maria.${stamp}@example.com`,
      app_consent: true,
    }),
  })
  for (const text of instructions) {
    const instruction = await call(`/patients/${created.body.id}/instructions`, { method: 'POST', token, body: JSON.stringify({ text }) })
    await call(`/instructions/${instruction.body.id}/analyze`, { method: 'POST', token })
    await call(`/instructions/${instruction.body.id}/generate`, { method: 'POST', token })
    await call(`/instructions/${instruction.body.id}/approve`, { method: 'POST', token })
  }
  return { id: created.body.id as string, inviteLink: created.body.app_invite.link as string }
}

export async function discharge(token: string, patientId: string) {
  await call(`/patients/${patientId}`, { method: 'PATCH', token, body: JSON.stringify({ admission_status: 'DISCHARGED' }) })
}

export async function bookAppointment(token: string, patientId: string, startsAt: Date) {
  return call(`/patients/${patientId}/appointments`, {
    method: 'POST',
    token,
    body: JSON.stringify({ title: 'Cardiology check-up', starts_at: startsAt.toISOString(), location: 'Clinic B, 2nd floor' }),
  })
}

export async function signInStaff(page: Page, token: string) {
  await page.goto('/login')
  await page.evaluate((t) => localStorage.setItem('safehaven.access_token', t), token)
}

/** Open the emailed link on this page's origin (the link names the configured dashboard). */
export function linkPath(link: string) {
  return link.replace(/^https?:\/\/[^/]+/, '')
}
