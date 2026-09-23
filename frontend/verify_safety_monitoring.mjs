// Module 3 — end-to-end verification of the wearable safety-monitoring flow.
//
// Drives a real browser against the real backend, in the same style as
// verify_all_flows.mjs. The device side is exercised through the real
// /device-api endpoints with a real per-device credential, so this covers the
// whole chain: staff UI -> assignment -> device event -> rules -> alert queue
// -> acknowledge, with nothing mocked.
//
//   npm run dev                 # frontend on :5173
//   uvicorn app.main:app        # backend on :8000
//   node verify_safety_monitoring.mjs
//
// Optional:
//   node verify_safety_monitoring.mjs --with-offline
//     Also exercises Scenario 6 (device offline). Off by default because it
//     has to outwait DEVICE_OFFLINE_AFTER_SECONDS in real time; start the
//     backend with DEVICE_OFFLINE_AFTER_SECONDS=10 to keep it quick.
//
// Covers demo Scenarios 1-7 from MODULE_3_IMPLEMENTATION_PLAN.md §29. The
// scenarios that must produce NOTHING are asserted just as hard as the ones
// that alert: avoiding false alarms is part of the safety story, not an
// optimisation (DOCUMENTATION.md §7 rule 6).

import { chromium } from 'playwright'

const APP = 'http://localhost:5173'
const API = 'http://localhost:8000'
const WITH_OFFLINE = process.argv.includes('--with-offline')

const stamp = Date.now()
const email = `wearcheck_${stamp}@safehaven.ai`
const password = 'supersecret123'
const DEVICE_A = `SH-E2E-${stamp}-A`
const DEVICE_B = `SH-E2E-${stamp}-B`

const STRONG_FALL = {
  fall_score: 4,
  peak_g: 4.025,
  tilt_delta_deg: 90.2,
  freefall_ms: 160,
  inactive_ms: 2520,
  stages_seen: ['freefall', 'impact', 'orientation', 'inactivity'],
}
// Sitting down hard: an impact and nothing else. Must stay silent.
const WEAK_FALL = { fall_score: 1, peak_g: 3.0, stages_seen: ['impact'] }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const consoleErrors = []
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })
page.on('pageerror', (err) => consoleErrors.push('PAGE ERROR: ' + err.message))

let failures = 0
async function step(name, fn) {
  try {
    await fn()
    console.log(`OK   ${name}`)
  } catch (err) {
    failures += 1
    console.log(`FAIL ${name}: ${err.message}`)
    await page.screenshot({ path: `/tmp/wearcheck_failure_${name.replace(/\W+/g, '_')}.png` })
    throw err
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const token = () => page.evaluate(() => localStorage.getItem('safehaven.access_token'))

async function api(path, { method = 'GET', body, bearer } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  headers.Authorization = `Bearer ${bearer ?? (await token())}`
  const resp = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  return { status: resp.status, body: await resp.json().catch(() => null) }
}

/** Register + enrol a device the same way a real one would: a clinician mints
 *  a single-use code, the device exchanges it for its own secret. */
async function enrolDevice(code) {
  const reg = await api('/wearable-devices', { method: 'POST', body: { device_code: code } })
  assert(reg.status === 201, `register ${code}: ${reg.status}`)
  const enrolled = await fetch(`${API}/device-api/enroll`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enrollment_code: reg.body.enrollment_code, hardware_id: `HW-${code}` }),
  })
  assert(enrolled.status === 200, `enrol ${code}: ${enrolled.status}`)
  return { id: reg.body.device.id, secret: (await enrolled.json()).device_secret }
}

async function deviceEvent(secret, id, type, metrics) {
  const resp = await fetch(`${API}/device-api/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${secret}` },
    body: JSON.stringify({
      device_event_id: id,
      event_type: type,
      occurred_at_ms: Date.now(),
      metrics: metrics ?? {},
    }),
  })
  return resp.status
}

async function heartbeat(secret, battery = 85) {
  await fetch(`${API}/device-api/heartbeat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${secret}` },
    body: JSON.stringify({ battery_percent: battery, firmware_version: '0.1.0' }),
  })
}

/** Cards currently on the alert queue, as the nurse sees them. */
async function alertCards() {
  return page.$$eval('[data-testid="safety-alert-card"]', (nodes) =>
    nodes.map((n) => ({
      type: n.getAttribute('data-alert-type'),
      priority: n.getAttribute('data-priority'),
      status: n.querySelector('[data-testid="alert-status-badge"]')?.getAttribute('data-status'),
      message: n.querySelector('[data-testid="safety-alert-message"]')?.textContent ?? '',
      events: n.querySelector('[data-testid="alert-event-count"]')?.textContent ?? '1 event',
      patient: n.textContent ?? '',
    })),
  )
}

// ── login ───────────────────────────────────────────────────────────────────

await step('register via API, log in through the real UI form', async () => {
  await fetch(`${API}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name: 'Wearable Check' }),
  })
  await page.goto(`${APP}/login`)
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button[type="submit"]')
  await page.waitForURL(`${APP}/patients`, { timeout: 15000 })
})

let patientId
let patientCode
await step('create a patient', async () => {
  await page.click('[data-testid="patient-new-button"]')
  await page.waitForSelector('input#first_name', { timeout: 10000 })
  await page.fill('input#first_name', 'Wear')
  await page.fill('input#last_name', 'Check')
  await page.fill('input#date_of_birth', '1948-03-02')
  await page.fill('#reason_for_visit', 'fall risk observation')
  await page.click('[data-testid="patient-create-submit"]')
  await page.waitForURL(/\/patients\/.+/, { timeout: 15000 })
  patientId = page.url().split('/patients/')[1]
  patientCode = (await api(`/patients/${patientId}`)).body.patient_code
})

let deviceA
let deviceB
await step('enrol two wearables through the real device API', async () => {
  deviceA = await enrolDevice(DEVICE_A)
  deviceB = await enrolDevice(DEVICE_B)
  await heartbeat(deviceA.secret)
  await heartbeat(deviceB.secret)
})

// ── Scenario 1 — assignment ────────────────────────────────────────────────

await step('SCENARIO 1: assign a wearable from the patient page', async () => {
  await page.reload()
  await page.waitForSelector('[data-testid="wearable-device-panel"]', { timeout: 15000 })
  await page.waitForSelector('[data-testid="no-wearable-assigned"]', { timeout: 10000 })

  await page.click('[data-testid="assign-device-trigger"]')
  await page.waitForSelector(`[data-device-code="${DEVICE_A}"]`, { timeout: 15000 })

  // Only free, enrolled devices are offered — never one already monitoring
  // someone else, which would fail with a 409 at the bedside.
  const offered = await page.$$eval('[data-testid="device-option"]', (n) =>
    n.map((e) => e.getAttribute('data-device-code')),
  )
  assert(offered.includes(DEVICE_A), 'device A not offered')
  assert(offered.includes(DEVICE_B), 'device B not offered')

  await page.click(`[data-device-code="${DEVICE_A}"]`)
  await page.click('[data-testid="monitoring-profile-select"]')
  // Role-scoped, not text=. Radix Select also renders a visually-hidden
  // native <option> for form compatibility, and a bare text selector matches
  // that one first — it sits behind the dialog overlay, so the click is
  // intercepted and times out.
  await page.getByRole('option', { name: 'Fall risk', exact: true }).click()
  await page.click('[data-testid="confirm-assign-device"]')

  await page.waitForSelector('[data-testid="wearable-assignment-row"]', { timeout: 15000 })
  const online = await page.getAttribute('[data-testid="wearable-online-state"]', 'data-online')
  assert(online === 'true', `device should be connected, got ${online}`)
})

// ── Scenario 2 / 3b — the events that must produce NOTHING ─────────────────

await step('SCENARIO 2: ordinary movement and a weak impact raise NO alert', async () => {
  assert((await deviceEvent(deviceA.secret, `w1-${stamp}`, 'POSSIBLE_FALL', WEAK_FALL)) === 201,
    'weak fall event should still be accepted and stored')
  assert((await deviceEvent(deviceA.secret, `w2-${stamp}`, 'POSSIBLE_FALL', WEAK_FALL)) === 201,
    'second weak fall should be accepted')

  await page.goto(`${APP}/safety-monitoring`)
  await page.waitForSelector('[data-testid="no-alerts"], [data-testid="safety-alert-card"]', { timeout: 15000 })
  // Give the poll a full cycle to prove nothing turns up later either.
  await page.waitForTimeout(4000)

  const mine = (await alertCards()).filter((c) => c.patient.includes(patientCode))
  assert(mine.length === 0, `expected no alerts, got ${JSON.stringify(mine)}`)
})

// ── Scenario 3 — possible fall, appearing WITHOUT a reload ─────────────────

await step('SCENARIO 3: a fall appears on the dashboard via polling, no reload', async () => {
  // Deliberately not reloading: this is the assertion that decision D1
  // (polling rather than WebSocket/SSE) actually delivers alerts to a nurse
  // who is just looking at the screen.
  for (let i = 0; i < 7; i += 1) {
    assert((await deviceEvent(deviceA.secret, `f${i}-${stamp}`, 'POSSIBLE_FALL', STRONG_FALL)) === 201,
      'fall event rejected')
  }

  await page.waitForFunction(
    (code) =>
      [...document.querySelectorAll('[data-testid="safety-alert-card"]')].some(
        (n) => n.getAttribute('data-alert-type') === 'POSSIBLE_FALL' && n.textContent.includes(code),
      ),
    patientCode,
    { timeout: 15000 },
  )

  const fall = (await alertCards()).find(
    (c) => c.type === 'POSSIBLE_FALL' && c.patient.includes(patientCode),
  )
  assert(fall.priority === 'HIGH', `fall should be HIGH, got ${fall.priority}`)
  assert(fall.message.includes('Possible fall detected'), `unexpected wording: ${fall.message}`)
  // One physical fall is ONE alert, however many events it produced.
  assert(/7 events/.test(fall.events), `expected 7 events folded, got "${fall.events}"`)
  assert(fall.patient.includes('Room'), 'alert card must show the room')
})

await step('alert wording never states a clinical cause', async () => {
  const text = (await alertCards()).map((c) => c.message.toLowerCase()).join(' ')
  for (const term of ['seizure', 'stroke', 'reaction', 'neurolog', 'left bed', 'out of bed', 'diagnos']) {
    assert(!text.includes(term), `alert wording contains a clinical claim: "${term}"`)
  }
})

await step('header badge reflects the live alert count', async () => {
  const badge = await page.textContent('[data-testid="safety-alert-count"]')
  assert(Number(badge) >= 1, `badge should show at least one alert, got "${badge}"`)
})

// ── Scenario 4 — abnormal movement ─────────────────────────────────────────

await step('SCENARIO 4: abnormal repetitive movement alerts without diagnosing', async () => {
  await deviceEvent(deviceA.secret, `a1-${stamp}`, 'ABNORMAL_MOVEMENT', {
    duration_s: 20.0, dom_freq_hz: 3.85, magnitude: 0.376, periodicity: 0.971,
  })
  await page.waitForFunction(
    (code) =>
      [...document.querySelectorAll('[data-testid="safety-alert-card"]')].some(
        (n) => n.getAttribute('data-alert-type') === 'ABNORMAL_MOVEMENT' && n.textContent.includes(code),
      ),
    patientCode,
    { timeout: 15000 },
  )
  const card = (await alertCards()).find(
    (c) => c.type === 'ABNORMAL_MOVEMENT' && c.patient.includes(patientCode),
  )
  assert(card.message.includes('Abnormal repetitive movement'), `wording: ${card.message}`)
  // FALL_RISK profile escalates this to HIGH.
  assert(card.priority === 'HIGH', `expected HIGH under FALL_RISK, got ${card.priority}`)
})

// ── Scenario 5 — mobility is gated on the profile ──────────────────────────

await step('SCENARIO 5: mobility is silent under FALL_RISK, alerts under RESTRICTED_MOBILITY', async () => {
  const before = await deviceEvent(deviceA.secret, `m1-${stamp}`, 'UNEXPECTED_MOBILITY', {})
  assert(before === 201, 'mobility event should be stored even when it will not alert')
  await page.waitForTimeout(4000)
  let mobility = (await alertCards()).filter(
    (c) => c.type === 'UNEXPECTED_MOBILITY' && c.patient.includes(patientCode),
  )
  assert(mobility.length === 0, 'mobility must NOT alert under FALL_RISK')

  // Switch the profile deliberately, then send the same signal again.
  await api(`/patients/${patientId}/wearable-assignment`, { method: 'DELETE' })
  await api(`/patients/${patientId}/wearable-assignment`, {
    method: 'POST',
    body: { device_id: deviceA.id, monitoring_profile: 'RESTRICTED_MOBILITY' },
  })
  await deviceEvent(deviceA.secret, `m2-${stamp}`, 'UNEXPECTED_MOBILITY', {})

  await page.waitForFunction(
    (code) =>
      [...document.querySelectorAll('[data-testid="safety-alert-card"]')].some(
        (n) => n.getAttribute('data-alert-type') === 'UNEXPECTED_MOBILITY' && n.textContent.includes(code),
      ),
    patientCode,
    { timeout: 15000 },
  )
  mobility = (await alertCards()).find(
    (c) => c.type === 'UNEXPECTED_MOBILITY' && c.patient.includes(patientCode),
  )
  // The most inferential signal must not outrank a possible fall.
  assert(mobility.priority === 'MEDIUM', `mobility should be MEDIUM, got ${mobility.priority}`)
  assert(mobility.message.includes('Unexpected mobility'), `wording: ${mobility.message}`)
})

// ── acknowledge ────────────────────────────────────────────────────────────

await step('a nurse can acknowledge an alert', async () => {
  const card = page
    .locator('[data-testid="safety-alert-card"]', { hasText: patientCode })
    .filter({ has: page.locator('[data-testid="acknowledge-alert"]') })
    .first()
  await card.locator('[data-testid="acknowledge-alert"]').click()
  await page.waitForFunction(
    (code) =>
      [...document.querySelectorAll('[data-testid="safety-alert-card"]')].some(
        (n) =>
          n.textContent.includes(code) &&
          n.querySelector('[data-testid="alert-status-badge"]')?.getAttribute('data-status') ===
            'ACKNOWLEDGED',
      ),
    patientCode,
    { timeout: 15000 },
  )
})

// ── event history shows suppressed events too ──────────────────────────────

await step('wearable event history includes events that did NOT alert', async () => {
  await page.goto(`${APP}/patients/${patientId}`)
  await page.click('[data-testid="patient-tab-safety-events"]')
  await page.waitForSelector('[data-testid="safety-event-row"]', { timeout: 15000 })
  const rows = await page.$$eval('[data-testid="safety-event-row"]', (n) =>
    n.map((e) => e.getAttribute('data-event-type')),
  )
  // 2 weak falls + 7 strong + 1 abnormal + 2 mobility = 12 stored events,
  // against far fewer alerts. Seeing the suppressed ones is how the silence
  // becomes trustworthy.
  assert(rows.length >= 12, `expected >=12 stored events, got ${rows.length}`)
})

// ── Scenario 6 — device offline (opt-in: needs real elapsed time) ──────────

if (WITH_OFFLINE) {
  await step('SCENARIO 6: a silent assigned device raises DEVICE_OFFLINE', async () => {
    const waitS = Number(process.env.OFFLINE_WAIT_S ?? 130)
    await page.goto(`${APP}/safety-monitoring`)
    // Stop heartbeating and let the threshold pass. The dashboard poll is the
    // sweep, so simply leaving this page open is what detects it.
    await page.waitForTimeout(waitS * 1000)
    await page.waitForFunction(
      (code) =>
        [...document.querySelectorAll('[data-testid="safety-alert-card"]')].some(
          (n) => n.getAttribute('data-alert-type') === 'DEVICE_OFFLINE' && n.textContent.includes(code),
        ),
      patientCode,
      { timeout: 20000 },
    )
    const offline = (await alertCards()).find((c) => c.type === 'DEVICE_OFFLINE')
    assert(offline.priority === 'HIGH', 'a silently dead monitor is a HIGH-priority condition')
  })
} else {
  console.log('SKIP SCENARIO 6 (device offline) — pass --with-offline to include it')
}

// ── Scenario 7 — discharge and reassignment ────────────────────────────────

await step('SCENARIO 7: discharge ends monitoring automatically', async () => {
  await page.goto(`${APP}/patients/${patientId}`)
  await page.waitForSelector('[data-testid="wearable-assignment-row"]', { timeout: 15000 })
  await page.click('[data-testid="discharge-button"]')
  await page.waitForSelector('[data-testid="no-wearable-assigned"]', { timeout: 15000 })

  const assignment = await api(`/patients/${patientId}/wearable-assignment`)
  assert(assignment.body.assignment === null, 'discharge must end the assignment')
})

await step('SCENARIO 7: the same physical device is reusable for another patient', async () => {
  const second = await api('/patients', {
    method: 'POST',
    body: {
      first_name: 'Reuse', last_name: 'Check', date_of_birth: '1951-04-04',
      preferred_language: 'ENGLISH', room_number: '221',
    },
  })
  const secondId = second.body.id

  const assigned = await api(`/patients/${secondId}/wearable-assignment`, {
    method: 'POST',
    body: { device_id: deviceA.id, monitoring_profile: 'STANDARD' },
  })
  assert(assigned.status === 201, `reassignment failed: ${assigned.status}`)

  await page.goto(`${APP}/patients/${secondId}`)
  await page.waitForSelector('[data-testid="wearable-assignment-row"]', { timeout: 15000 })
  const code = await page.getAttribute('[data-testid="wearable-assignment-row"]', 'data-device-code')
  assert(code === DEVICE_A, `expected ${DEVICE_A} on the new patient, got ${code}`)

  // And the old patient retains no active association.
  const old = await api(`/patients/${patientId}/wearable-assignment`)
  assert(old.body.assignment === null, 'discharged patient must keep no active assignment')
})

// ── wrap up ────────────────────────────────────────────────────────────────

// The 401 the app deliberately triggers on an expired session is logged by the
// browser as a console error; nothing here should produce one.
const realErrors = consoleErrors.filter((e) => !e.includes('401'))
if (realErrors.length) {
  failures += 1
  console.log(`FAIL console errors:\n  ${realErrors.join('\n  ')}`)
} else {
  console.log('OK   no console errors')
}

await browser.close()
console.log(failures === 0 ? '\nAll safety-monitoring checks passed.' : `\n${failures} check(s) failed.`)
process.exit(failures === 0 ? 0 : 1)
