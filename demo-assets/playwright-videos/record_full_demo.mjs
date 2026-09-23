/**
 * Records the full SafeHaven AI walkthrough, with on-screen caption cards
 * explaining each feature as it's demonstrated.
 *
 * Prerequisites: backend on :8000 (LLM_PROVIDER=openai), frontend on :5173.
 * Run from the frontend directory so `playwright` resolves.
 */
import { existsSync } from 'node:fs'
import { chromium } from 'playwright'

const APP = 'http://localhost:5173'
const API = 'http://localhost:8000'
const OUT_DIR = '/Users/sai/Desktop/safehaven-ai/demo-assets/playwright-videos'
const SPEECH_WAV = '/Users/sai/Desktop/safehaven-ai/demo-assets/dictation-speech.wav'

const stamp = Date.now()
const nurseEmail = `demo.nurse.${stamp}@safehaven.ai`
const pharmEmail = `demo.pharmacist.${stamp}@safehaven.ai`
const password = 'supersecret123'

const pause = (ms) => new Promise((r) => setTimeout(r, ms))

// Without this the failure is silent and baffling: Chromium falls back to a
// silent fake microphone, and the transcription model hallucinates a sentence
// in an arbitrary language rather than returning nothing.
if (!existsSync(SPEECH_WAV)) {
  throw new Error(`Dictation audio missing: ${SPEECH_WAV}. Regenerate it before recording.`)
}

const browser = await chromium.launch({
  slowMo: 90,
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${SPEECH_WAV}`,
  ],
})
// Declared here, created only once the off-camera setup below is finished —
// otherwise the recorder captures a minute of blank page while the setup's
// real AI calls run.
let context
let page

// How long a caption card stays up.
//
// These cards are dense — the longest runs to 33 words — and a viewer gets one
// pass at them with no scrubbing. The previous flat 3200ms worked out at
// 470-530 wpm on the longer cards, about double a comfortable reading speed,
// so in practice they could not be read.
//
// Duration is now derived from the text: a short beat to notice the card has
// appeared, plus reading time at CAPTION_WPM. Override for a faster or slower
// cut without touching any call site:
//
//     CAPTION_WPM=260 node record_full_demo.mjs   # snappier
//     CAPTION_WPM=180 node record_full_demo.mjs   # slower, for a non-native
//                                                 # or non-technical audience
const CAPTION_WPM = Number(process.env.CAPTION_WPM ?? 220)
const CAPTION_LEAD_IN_MS = 1300

/**
 * An explicit `ms` argument is treated as a FLOOR, not an override, so the few
 * cards deliberately given extra weight keep that emphasis while still never
 * being held for less than they take to read.
 */
function captionMs(title, body, floor = 0) {
  const words = `${title} ${body}`.trim().split(/\s+/).length
  const read = CAPTION_LEAD_IN_MS + Math.round((words / CAPTION_WPM) * 60_000)
  return Math.max(read, floor)
}

/** Full-screen explanation card, so the video is self-describing. */
async function caption(title, body, floorMs = 0) {
  const ms = captionMs(title, body, floorMs)
  await page.evaluate(
    ({ title, body }) => {
      document.getElementById('__cap__')?.remove()
      const el = document.createElement('div')
      el.id = '__cap__'
      el.style.cssText =
        'position:fixed;inset:0;z-index:2147483647;background:#0f172a;color:#fff;display:flex;' +
        'flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 80px;' +
        'font-family:ui-sans-serif,system-ui,-apple-system,sans-serif'
      el.innerHTML =
        `<div style="font-size:46px;font-weight:700;letter-spacing:-.02em;margin-bottom:18px">${title}</div>` +
        `<div style="font-size:23px;line-height:1.55;opacity:.85;max-width:880px">${body}</div>`
      document.body.appendChild(el)
    },
    { title, body },
  )
  await pause(ms)
  await page.evaluate(() => document.getElementById('__cap__')?.remove())
  await pause(250)
}

async function type(selector, text, delay = 55) {
  await page.click(selector)
  await page.locator(selector).pressSequentially(text, { delay })
}

async function api(path, options = {}, token) {
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })
  return res.json().catch(() => ({}))
}

/**
 * Creates an approved order off-camera.
 *
 * Retries on NEEDS_REVIEW because that is not an error: it means the
 * deterministic fact-preservation check rejected that particular AI
 * generation, which is the safety layer doing its job. The designed recovery
 * is a new version, so each retry starts a fresh instruction.
 */
async function approvedOrder(token, patientId, text, attempts = 3) {
  for (let attempt = 1; attempt <= attempts; attempt++) {
    const created = await api(`/patients/${patientId}/instructions`, { method: 'POST', body: JSON.stringify({ text }) }, token)
    await api(`/instructions/${created.id}/analyze`, { method: 'POST' }, token)
    const gen = await api(`/instructions/${created.id}/generate`, { method: 'POST' }, token)
    if (gen.status === 'READY_FOR_APPROVAL') {
      await api(`/instructions/${created.id}/approve`, { method: 'POST' }, token)
      return created
    }
    console.log(`  (retry ${attempt}/${attempts}: validation rejected a generation for "${text.slice(0, 40)}…")`)
    // Leave the rejected instruction unapproved — it never reaches the patient.
  }
  throw new Error(`generation never passed validation for "${text}" after ${attempts} attempts`)
}

async function makePatient(token, first, last, dob, room, language = 'ENGLISH') {
  return api(
    '/patients',
    { method: 'POST', body: JSON.stringify({ first_name: first, last_name: last, date_of_birth: dob, room_number: room, preferred_language: language }) },
    token,
  )
}

// ---------------------------------------------------------------------------
// Setup done off-camera: accounts, plus the patients used only to demonstrate
// the Module 2 safety scenarios. The main patient is created on camera.
// ---------------------------------------------------------------------------
for (const email of [nurseEmail, pharmEmail]) {
  await api('/auth/register', { method: 'POST', body: JSON.stringify({ email, password, full_name: email.includes('pharm') ? 'Priya Nair (Pharmacist)' : 'Sam Okafor (Nurse)' }) })
}
const { access_token: token } = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: nurseEmail, password }) })

// Allergy-block demo patient
const allergyPatient = await makePatient(token, 'Rahul', 'Menon', '1958-02-14', '204')
await api(`/patients/${allergyPatient.id}/allergies`, { method: 'POST', body: JSON.stringify({ allergen: 'Metoprolol', reaction: 'severe wheezing' }) }, token)
await approvedOrder(token, allergyPatient.id, 'Take Metoprolol Succinate ER 25 mg orally twice daily.')

// Drug-interaction demo patient
const interactionPatient = await makePatient(token, 'Grace', 'Adeyemi', '1949-06-30', '206')
await approvedOrder(token, interactionPatient.id, 'Take Metoprolol Succinate ER 25 mg orally twice daily.')
await approvedOrder(token, interactionPatient.id, 'Take Diltiazem 120 mg orally once daily.')

// High-alert co-sign demo patient
const highAlertPatient = await makePatient(token, 'Tomas', 'Silva', '1952-10-05', '208')
await approvedOrder(token, highAlertPatient.id, 'Take Warfarin 5 mg orally once daily.')

// PRN demo patient
const prnPatient = await makePatient(token, 'Nadia', 'Haddad', '1970-01-20', '210')
await approvedOrder(token, prnPatient.id, 'Take Paracetamol 500 mg orally every 6 hours as needed for pain.')

// Stopped-vs-completed demo patient: one drug withdrawn, one course finished.
const stoppedPatient = await makePatient(token, 'Marcus', 'Bell', '1947-07-19', '216')
const withdrawn = await approvedOrder(token, stoppedPatient.id, 'Take Metoprolol Succinate ER 25 mg orally twice daily.')
const finished = await approvedOrder(token, stoppedPatient.id, 'Take Lisinopril 10 mg orally once daily.')
await api(`/instructions/${withdrawn.id}/clinical-status`, { method: 'PATCH', body: JSON.stringify({ status: 'STOPPED' }) }, token)
await api(`/instructions/${finished.id}/clinical-status`, { method: 'PATCH', body: JSON.stringify({ status: 'COMPLETED' }) }, token)
const stoppedLink = await api(`/patients/${stoppedPatient.id}/care-access-tokens`, { method: 'POST' }, token)

// Discharged patient — orders stay on file, but no dose may be given.
const dischargedPatient = await makePatient(token, 'Ingrid', 'Olsen', '1951-12-02', '218')
await approvedOrder(token, dischargedPatient.id, 'Take Metoprolol Succinate ER 25 mg orally twice daily.')
await api(`/patients/${dischargedPatient.id}`, { method: 'PATCH', body: JSON.stringify({ admission_status: 'DISCHARGED' }) }, token)

// ---------------------------------------------------------------------------
// Recording starts here — nothing above this line is captured.
// ---------------------------------------------------------------------------
context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  permissions: ['microphone'],
  recordVideo: { dir: OUT_DIR, size: { width: 1280, height: 800 } },
})
page = await context.newPage()

await page.goto(`${APP}/login`)
await page.waitForSelector('#email')

await caption('SafeHaven AI', 'A patient-safety platform with two modules: helping patients understand their medications, and verifying every dose before it is given.', 4000)

await caption('Module 1 — Clinician sign-in', 'Every action is attributed to a named clinician and recorded on an audit trail.')
await type('#email', nurseEmail)
await type('#password', password)
await pause(400)
await page.click('[data-testid="login-submit"]')
await page.waitForURL(`${APP}/patients`, { timeout: 15000 })
await pause(900)

await caption('Registering a patient', 'The patient picks their own language — SafeHaven supports 11, including right-to-left scripts.')
await page.click('[data-testid="patient-new-button"]')
await page.waitForSelector('#first_name')
await type('#first_name', 'Elena')
await type('#last_name', 'Ruiz')
await page.fill('#date_of_birth', '1966-08-08')
await type('#room_number', '212')
await page.click('[data-testid="preferred-language-select"]')
await pause(700)
await page.click('[data-testid="preferred-language-option-spanish"]')
await pause(600)
await page.click('[data-testid="patient-create-submit"]')
await page.waitForURL(/\/patients\/.+/, { timeout: 15000 })
const patientId = page.url().split('/patients/')[1]
const patient = await api(`/patients/${patientId}`, {}, token)
await pause(900)

await caption('Allergies and conditions', 'Allergies are checked automatically before every dose. Conditions drive a plain-language explainer for the patient.')
await page.waitForSelector('[data-testid="allergy-input"]')
await type('[data-testid="allergy-input"]', 'Penicillin')
await page.click('[data-testid="allergy-add-button"]')
await page.waitForSelector('[data-testid="allergy-badge"]', { timeout: 10000 })
await pause(700)
await type('[data-testid="condition-input"]', 'Hypertension')
await page.click('[data-testid="condition-add-button"]')
await page.waitForSelector('[data-testid="condition-badge"]', { timeout: 10000 })
await pause(1200)

await caption('Writing an order by voice', 'The clinician dictates instead of typing. The transcript arrives as an editable draft — it is never submitted automatically.')
await page.click('[data-testid="instruction-new-button"]')
await page.waitForSelector('[data-testid="dictate-button"]', { timeout: 10000 })
// Chromium's fake microphone loops the source file continuously, so a
// capture window can open mid-sentence and catch mostly silence — on which
// transcription models are known to hallucinate (one take came back as
// Vietnamese). Record comfortably longer than the 5.5s source so at least one
// clean pass of the sentence is always inside the window, then verify what
// landed and retake if it is wrong. The app handles a bad transcript
// correctly either way; this is only so the recording shows the happy path.
for (let take = 1; take <= 3; take++) {
  await page.click('[data-testid="dictate-button"]')
  await page.waitForSelector('[data-testid="dictate-recording-indicator"]', { timeout: 10000 })
  await pause(9500)
  await page.click('[data-testid="dictate-stop-button"]')
  await page.waitForSelector('[data-testid="dictate-review-notice"]', { timeout: 60000 })

  const heard = await page.locator('#text').inputValue()
  if (/metoprolol/i.test(heard)) break
  console.log(`  (dictation take ${take} misheard as "${heard.slice(0, 60)}" — retaking)`)
  if (take === 3) throw new Error(`dictation never transcribed cleanly; last take: ${heard}`)
  await page.fill('#text', '')
}
await pause(2600)

await caption('Why the clinician must still read it', 'A mis-heard dose would become the order every later check compares against — so no automated check could catch it. The clinician is the safeguard here.', 4200)

await page.click('[data-testid="instruction-create-submit"]')
await page.waitForURL(/\/instructions\/.+/, { timeout: 15000 })

await caption('AI extracts the facts — code decides', 'The AI proposes. Deterministic validation compares every fact back against the original before a clinician can approve it.')
await page.waitForSelector('[data-testid="approve-button"]', { timeout: 90000 })
await pause(1800)
await page.evaluate(() => document.querySelector('[data-testid="reading-grade-level"]')?.scrollIntoView({ block: 'center' }))
await pause(2400)

await caption('Reading level is measured', 'Patient materials should sit around a 6th-grade reading level. The score is shown to the clinician before approval.')
await page.waitForSelector('[data-testid="ai-processing-overlay"]', { state: 'detached', timeout: 15000 }).catch(() => {})
await page.click('[data-testid="approve-button"]')
await page.waitForSelector('text=/APPROVED/i', { timeout: 15000 })
await pause(1400)

// --- Patient view -----------------------------------------------------------
const careLink = await api(`/patients/${patientId}/care-access-tokens`, { method: 'POST' }, token)

await caption('Module 1 — what the patient sees', 'The patient opens a private link. No login, no app install.')
await page.goto(`${APP}/care?token=${careLink.token}`)
await page.waitForSelector('[data-testid="patient-allergies-card"]', { timeout: 20000 })
await pause(2600)

await caption('Their allergies, shown back to them', 'The patient is the one person who can notice the list is wrong — so the page asks them to speak up.')
await pause(1600)

await page.click('[data-testid="understand-medicine-button"]')
await pause(1600)
await caption('What it is, and why they are taking it', 'Either the reason the clinician documented, or clearly-labelled general reference information. Never inferred for this patient.')
await page.evaluate(() => document.querySelector('[data-testid="why-explanation"]')?.scrollIntoView({ block: 'center' }))
await pause(2600)

await caption('Checking understanding properly', 'Instead of a "yes I understand" button, the patient explains it back in their own words — the teach-back method.')
await page.evaluate(() => document.querySelector('[data-testid="comprehension-feedback"]')?.scrollIntoView({ block: 'center' }))
await pause(800)
await page.click('[data-testid="comprehension-feedback-button"][data-response="UNDERSTOOD"]')
await page.waitForSelector('[data-testid="teach-back-prompt"]', { timeout: 10000 })
await pause(1200)
await type('[data-testid="teach-back-input"]', 'I take a pill every day.', 45)
await pause(600)
await page.click('[data-testid="teach-back-submit"]')
await page.waitForSelector('[data-testid="teach-back-result"]', { timeout: 15000 })
await pause(3000)

await caption('Their condition, in plain language', 'A curated explainer — what it is, how it develops, where it affects them. Written by people, never generated.')
await page.evaluate(() => document.querySelector('[data-testid="condition-explainer-card"]')?.scrollIntoView({ block: 'center' }))
await pause(3200)

await caption('The same care plan, in their language', 'Every translation passes the same fact-preservation check as the English original.')
await page.evaluate(() => window.scrollTo({ top: 0 }))
await pause(500)
await page.click('[data-testid="care-language-button-spanish"]')
await pause(2600)
await page.click('[data-testid="care-language-button-arabic"]')
await pause(2800)
await page.click('[data-testid="care-language-button-english"]')
await pause(800)

await caption('When a medication is stopped', 'A drug the team withdrew and a course the patient finished both sit in their history — but only one of them needs the patient to act.', 3600)
await page.goto(`${APP}/care?token=${stoppedLink.token}`)
await page.waitForSelector('[data-testid="past-medication-row"]', { timeout: 20000 })
await page.evaluate(() => document.querySelector('[data-past-reason="STOPPED"]')?.scrollIntoView({ block: 'center' }))
await pause(3800)

// --- Module 2 ---------------------------------------------------------------
await caption('Module 2 — verifying a dose at the bedside', 'Every check from here is deterministic code comparing the scan against the order. No AI decides anything.', 4000)

async function startScan(patientCode) {
  await page.goto(`${APP}/medication-verification`)
  await page.waitForSelector('[data-testid="patient-id-mode-enter"]', { timeout: 15000 })
  await page.click('[data-testid="patient-id-mode-enter"]')
  await type('[data-testid="patient-id-manual-input"]', patientCode, 40)
  await page.click('[data-testid="patient-id-manual-submit"]')
  await page.waitForSelector('[data-testid="patient-confirm-identity-button"]', { timeout: 15000 })
}

async function scanMedication(barcode) {
  await page.click('[data-testid="medication-id-mode-enter"]')
  await type('[data-testid="medication-id-manual-input"]', barcode, 30)
  await page.click('[data-testid="medication-id-manual-submit"]')
  await page.waitForSelector('[data-testid="verification-banner"]', { timeout: 20000 })
}

await caption('Two patient identifiers', 'Joint Commission requires two. Scanning the wristband is only the first — the nurse must confirm name and date of birth.')
await startScan(patient.patient_code)
await pause(2400)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await pause(900)

await caption('A correct dose', 'Patient, drug, dose, route, formulation, timing and interactions all checked against the live order.')
await scanMedication('MED-METOPROLOL-SUCCINATE-25')
await pause(3000)
await page.click('[data-testid="confirm-administration-button"]')
await page.waitForSelector('text=Administration confirmed', { timeout: 15000 })
await pause(2000)

await caption('Safety check 1 — a documented allergy', 'Rahul Menon is allergic to Metoprolol. Even a perfectly correct dose is blocked.')
await startScan(allergyPatient.patient_code)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await scanMedication('MED-METOPROLOL-SUCCINATE-25')
await pause(3600)

await caption('Safety check 2 — a drug interaction', 'Grace Adeyemi is already on Diltiazem. Combining it with a beta-blocker can dangerously slow the heart.')
await startScan(interactionPatient.patient_code)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await scanMedication('MED-METOPROLOL-SUCCINATE-25')
await pause(3600)

await caption('Safety check 3 — high-alert medication', 'Warfarin is on the ISMP high-alert list. A second clinician must independently authenticate before the dose is given.')
await startScan(highAlertPatient.patient_code)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await scanMedication('MED-WARFARIN-5')
await pause(2200)
await type('[data-testid="co-signer-email-input"]', pharmEmail, 25)
await type('[data-testid="co-signer-password-input"]', password, 30)
await pause(800)
await page.click('[data-testid="confirm-administration-button"]')
await page.waitForSelector('text=Administration confirmed', { timeout: 15000 })
await pause(2000)

await caption('Safety check 4 — an as-needed medication', 'A scheduled dose is justified by its schedule. An as-needed dose is not — so the reason is recorded with it.')
await startScan(prnPatient.patient_code)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await scanMedication('MED-PARACETAMOL-500')
await pause(1800)
await type('[data-testid="administration-reason-input"]', 'pain 7/10', 60)
await pause(800)
await page.click('[data-testid="confirm-administration-button"]')
await page.waitForSelector('text=Administration confirmed', { timeout: 15000 })
await pause(2200)

await caption('Safety check 5 — the patient has been discharged', 'Discharge deliberately leaves the orders on file. It must not leave them administrable.', 3600)
await startScan(dischargedPatient.patient_code)
await pause(2600)
await page.click('[data-testid="patient-confirm-identity-button"]')
await page.waitForSelector('[data-testid="medication-id-mode-enter"]', { timeout: 15000 })
await scanMedication('MED-METOPROLOL-SUCCINATE-25')
await pause(3600)

await caption('Every step is on the record', 'Who scanned, who administered, who co-signed — and every blocked attempt, in plain language, flagged as a safety event.')
await page.goto(`${APP}/patients/${allergyPatient.id}`)
await page.waitForSelector('[data-testid="patient-tab-activity"]', { timeout: 15000 })
await page.click('[data-testid="patient-tab-activity"]')
await page.waitForSelector('[data-testid="timeline-row"]', { timeout: 15000 })
await pause(3400)

await caption('SafeHaven AI', 'AI proposes. Deterministic code decides. A clinician approves. Nothing reaches a patient unchecked.', 4200)

await context.close()
await browser.close()
console.log('Recording complete.')
