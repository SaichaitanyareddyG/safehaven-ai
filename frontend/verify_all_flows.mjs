import { chromium } from 'playwright'

const APP = 'http://localhost:5173'
const LABEL_IMAGE = '/Users/sai/Desktop/safehaven-ai/demo-assets/label-metoprolol-succinate-25.png'

const email = `flowcheck_${Date.now()}@safehaven.ai`
const password = 'supersecret123'

const browser = await chromium.launch()
const page = await browser.newPage()
const consoleErrors = []
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })
page.on('pageerror', (err) => consoleErrors.push('PAGE ERROR: ' + err.message))

async function step(name, fn) {
  try {
    await fn()
    console.log(`OK   ${name}`)
  } catch (err) {
    console.log(`FAIL ${name}: ${err.message}`)
    await page.screenshot({ path: `/tmp/flowcheck_failure_${name.replace(/\W+/g, '_')}.png` })
    throw err
  }
}

// --- Real login through the actual UI form (exercises CORS + rate limit + JWT live) ---
await step('register via API, login via real UI form', async () => {
  await fetch('http://localhost:8000/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, full_name: 'Flow Check' }),
  })
  await page.goto(`${APP}/login`)
  await page.fill('input[type="email"]', email)
  await page.fill('input[type="password"]', password)
  await page.click('button[type="submit"]')
  await page.waitForURL(`${APP}/patients`, { timeout: 10000 })
})

let patientCode
await step('create a new patient', async () => {
  await page.click('[data-testid="patient-new-button"]')
  await page.waitForSelector('input#first_name', { timeout: 10000 })
  await page.fill('input#first_name', 'Flow')
  await page.fill('input#last_name', 'Check')
  await page.fill('input#date_of_birth', '1960-01-01')
  // Registration now asks why the patient came in, and requires it.
  await page.fill('#reason_for_visit', 'routine review')
  await page.click('[data-testid="patient-create-submit"]')
  await page.waitForURL(/\/patients\/.+/, { timeout: 10000 })
  const url = page.url()
  const patientId = url.split('/patients/')[1]
  const resp = await fetch(`http://localhost:8000/patients/${patientId}`, {
    headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('safehaven.access_token'))}` },
  })
  patientCode = (await resp.json()).patient_code
})

await step('create + auto-analyze + auto-generate + approve an instruction', async () => {
  await page.click('[data-testid="instruction-new-button"]')
  await page.waitForSelector('textarea', { timeout: 10000 })
  await page.fill('textarea', 'Take Metoprolol Succinate ER 25 mg orally twice daily.')
  await page.click('[data-testid="instruction-create-submit"]')
  await page.waitForURL(/\/instructions\/.+/, { timeout: 10000 })
  await page.waitForSelector('[data-testid="approve-button"]', { timeout: 45000 })
  await page.click('[data-testid="approve-button"]')
  await page.waitForSelector('text=/APPROVED/i', { timeout: 10000 })
})

await step('Medication Verification: identify patient by manual entry, confirm identity', async () => {
  await page.click('text=Medication Verification')
  await page.waitForSelector('[data-testid="patient-id-mode-enter"]', { timeout: 10000 })
  await page.click('[data-testid="patient-id-mode-enter"]')
  await page.fill('[data-testid="patient-id-manual-input"]', patientCode)
  await page.click('[data-testid="patient-id-manual-submit"]')
  // Second identifier check (name + DOB) — must be actively confirmed
  // before the medication step unlocks.
  await page.waitForSelector('[data-testid="patient-confirm-identity-button"]', { timeout: 10000 })
  await page.click('[data-testid="patient-confirm-identity-button"]')
  await page.waitForSelector('text=Step 3', { timeout: 10000 })
})

await step('scan medication by manual barcode entry -> VERIFIED', async () => {
  await page.click('[data-testid="medication-id-mode-enter"]')
  await page.fill('[data-testid="medication-id-manual-input"]', 'MED-METOPROLOL-SUCCINATE-25')
  await page.click('[data-testid="medication-id-manual-submit"]')
  await page.waitForSelector('[data-testid="verification-banner"]', { timeout: 15000 })
  const bannerText = await page.locator('[data-testid="verification-banner"]').innerText()
  if (!bannerText.includes('VERIFIED')) throw new Error(`expected VERIFIED, got: ${bannerText}`)
})

await step('confirm administration', async () => {
  await page.click('[data-testid="confirm-administration-button"]')
  await page.waitForSelector('text=Administration confirmed', { timeout: 10000 })
})

await step('start over -> image fallback path on a second patient', async () => {
  await page.click('[data-testid="start-over-button"]')
  await page.waitForSelector('[data-testid="patient-id-mode-enter"]', { timeout: 10000 })
  await page.click('[data-testid="patient-id-mode-enter"]')
  await page.fill('[data-testid="patient-id-manual-input"]', patientCode)
  await page.click('[data-testid="patient-id-manual-submit"]')
  await page.waitForSelector('[data-testid="patient-confirm-identity-button"]', { timeout: 10000 })
  await page.click('[data-testid="patient-confirm-identity-button"]')
  await page.waitForSelector('text=Step 3', { timeout: 10000 })
  await page.setInputFiles('[data-testid="image-fallback-file-input"]', LABEL_IMAGE)
  await page.waitForSelector('[data-testid="image-fallback-candidate"]', { timeout: 20000 })
  await page.click('[data-testid="confirm-candidate-button"]')
  await page.waitForSelector('[data-testid="verification-banner"]', { timeout: 15000 })
})

await step('patient care page loads (Module 1 patient-facing view)', async () => {
  const token = await fetch(`http://localhost:8000/patients`, {
    headers: { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('safehaven.access_token'))}` },
  }).then(r => r.json())
  const pid = token.results.find(p => p.patient_code === patientCode).id
  const authHeader = { Authorization: `Bearer ${await page.evaluate(() => localStorage.getItem('safehaven.access_token'))}` }
  const careLink = await fetch(`http://localhost:8000/patients/${pid}/care-access-tokens`, { method: 'POST', headers: authHeader }).then(r => r.json())
  await page.goto(`${APP}/care?token=${careLink.token}`)
  await page.waitForSelector('text=Today', { timeout: 10000 })
})

console.log('')
console.log(consoleErrors.length ? `CONSOLE ERRORS FOUND:\n${consoleErrors.join('\n')}` : 'No console errors across the whole run.')
console.log('ALL FLOWS PASSED')
await browser.close()
