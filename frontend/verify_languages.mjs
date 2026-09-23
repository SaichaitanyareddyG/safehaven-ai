import { chromium } from 'playwright'

const APP = 'http://localhost:5173'
const API = 'http://localhost:8000'
const email = `langs_${Date.now()}@safehaven.ai`
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
    await page.screenshot({ path: `/tmp/langs_failure_${name.replace(/\W+/g, '_')}.png` })
    throw err
  }
}

await fetch(`${API}/auth/register`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password, full_name: 'Language Check' }),
})
const { access_token: token } = await fetch(`${API}/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email, password }),
}).then((r) => r.json())
const authHeaders = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` }

// Spanish is the #1 US LEP language; Arabic exercises a non-Latin RTL script.
const TARGETS = ['SPANISH', 'ARABIC']

let careToken
await step('create a Spanish-preference patient and translate a real instruction', async () => {
  const patient = await fetch(`${API}/patients`, {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({
      first_name: 'Elena',
      last_name: 'Ruiz',
      date_of_birth: '1966-08-08',
      preferred_language: 'SPANISH',
    }),
  }).then((r) => r.json())
  if (patient.preferred_language !== 'SPANISH') throw new Error('patient language not persisted')

  const created = await fetch(`${API}/patients/${patient.id}/instructions`, {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({ text: 'Take Lisinopril 10 mg orally once daily for your blood pressure.' }),
  }).then((r) => r.json())
  await fetch(`${API}/instructions/${created.id}/analyze`, { method: 'POST', headers: authHeaders })
  const gen = await fetch(`${API}/instructions/${created.id}/generate`, { method: 'POST', headers: authHeaders }).then((r) => r.json())
  if (gen.status !== 'READY_FOR_APPROVAL') throw new Error(`generation failed: ${JSON.stringify(gen)}`)
  await fetch(`${API}/instructions/${created.id}/approve`, { method: 'POST', headers: authHeaders })

  // Real translations through the real validation pipeline.
  const results = await fetch(`${API}/instructions/${created.id}/translations`, {
    method: 'POST',
    headers: authHeaders,
    body: JSON.stringify({ languages: TARGETS }),
  }).then((r) => r.json())

  for (const language of TARGETS) {
    const status = results[language]?.status
    console.log(`  ${language}: validation ${status}`)
    if (status !== 'PASSED') {
      throw new Error(`${language} translation did not pass fact-preservation: ${JSON.stringify(results[language])}`)
    }
  }

  careToken = (await fetch(`${API}/patients/${patient.id}/care-access-tokens`, {
    method: 'POST',
    headers: authHeaders,
  }).then((r) => r.json())).token
})

await step('patient page renders Spanish by default and offers all 11 languages', async () => {
  await page.goto(`${APP}/care?token=${careToken}`)
  await page.waitForSelector('[data-testid="care-instruction-text"], [data-testid="current-medication-summary"]', { timeout: 15000 })

  const buttons = await page.locator('[data-testid^="care-language-button-"]').count()
  if (buttons !== 11) throw new Error(`expected 11 language buttons, got ${buttons}`)

  await page.click('[data-testid="understand-medicine-button"]')
  const spanish = await page.locator('[data-testid="care-instruction-text"]').innerText()
  console.log('  Spanish:', spanish.slice(0, 80))
  if (!/[áéíóúñ¿¡]/i.test(spanish)) throw new Error(`text does not look Spanish: ${spanish}`)
})

await step('switching to Arabic renders RTL', async () => {
  await page.click('[data-testid="care-language-button-arabic"]')
  const el = page.locator('[data-testid="care-instruction-text"]')
  const arabic = await el.innerText()
  const dir = await el.getAttribute('dir')
  console.log('  Arabic:', arabic.slice(0, 60), '| dir =', dir)
  if (!/[؀-ۿ]/.test(arabic)) throw new Error('text is not Arabic script')
  if (dir !== 'rtl') throw new Error(`expected dir="rtl", got ${dir}`)
})

await step('no horizontal overflow at phone width with 11 languages', async () => {
  await page.setViewportSize({ width: 390, height: 844 })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  if (overflow) throw new Error('page scrolls horizontally on a phone-width screen')
})

console.log('')
console.log(consoleErrors.length ? `CONSOLE ERRORS:\n${consoleErrors.join('\n')}` : 'No console errors.')
console.log('LANGUAGES VERIFIED LIVE')
await browser.close()
