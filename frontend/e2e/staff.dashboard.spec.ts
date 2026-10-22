import { expect, test } from '@playwright/test'

import { newPatientWithApp, newStaff, signInStaff } from './helpers'

test('register a patient with an app invite, English only', async ({ page }) => {
  const staff = await newStaff()
  await signInStaff(page, staff.token)
  await page.goto('/patients')
  await page.getByTestId('patient-new-button').click()

  await expect(page.locator('#preferred_language')).toHaveCount(0)
  await page.fill('#first_name', 'Ana')
  await page.fill('#last_name', `Ruiz${Date.now() % 1000}`)
  await page.fill('#date_of_birth', '1950-05-05')
  await page.fill('#reason_for_visit', 'Pneumonia')
  await page.fill('#email', `ana.${Date.now()}@example.com`)
  await page.getByTestId('patient-app-consent').check()
  await expect(page.getByTestId('patient-create-submit')).toHaveText('Register and send invite')
  await page.getByTestId('patient-create-submit').click()

  await expect(page).toHaveURL(/\/patients\/[0-9a-f-]+$/)
  await expect(page.getByTestId('patient-app-panel')).toContainText('Invite sent')
})

test('book and cancel an appointment', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token)
  await signInStaff(page, staff.token)
  await page.goto(`/patients/${patient.id}`)

  await page.getByTestId('appointment-add').click()
  await page.fill('#appt-title', 'Wound check')
  const d = new Date(Date.now() + 2 * 86400000)
  const pad = (n: number) => String(n).padStart(2, '0')
  await page.fill('#appt-when', `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T14:00`)
  await page.getByTestId('appointment-save').click()
  await expect(page.getByTestId('appointment-row')).toContainText('Wound check')

  await page.getByRole('button', { name: 'Cancel Wound check' }).click()
  await expect(page.getByTestId('appointment-row')).toContainText('Cancelled')
})

test('signed out after 15 minutes idle, with a warning first', async ({ page }) => {
  const staff = await newStaff()
  await page.clock.install()
  await signInStaff(page, staff.token)
  await page.goto('/patients')
  await expect(page.getByTestId('patient-new-button')).toBeVisible()

  await page.clock.fastForward('14:10')
  await expect(page.getByTestId('idle-warning')).toBeVisible()
  await page.getByTestId('idle-stay').click()
  await expect(page.getByTestId('idle-warning')).toHaveCount(0)

  await page.clock.fastForward('16:00')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByTestId('idle-signed-out')).toBeVisible()
})

test('add a caregiver who gets their own sign-in', async ({ page, browser }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, ['Take Metoprolol 25 mg orally twice daily with food.'])
  await signInStaff(page, staff.token)
  await page.goto(`/patients/${patient.id}`)

  await page.getByTestId('caregiver-add').click()
  await page.fill('#cg-name', 'Priya')
  await page.fill('#cg-rel', 'daughter')
  await page.fill('#cg-email', `priya.${Date.now()}@example.com`)
  await page.getByTestId('caregiver-consent').check()
  await page.getByTestId('caregiver-invite').click()
  await expect(page.getByTestId('caregiver-row')).toContainText('Priya')

  // Email is not set up on the test server, so the link is shown to staff.
  const link = await page.getByTestId('caregivers-section').locator('input[readonly]').inputValue()
  const phone = await browser.newPage()
  await phone.goto(link.replace(/^https?:\/\/[^/]+/, ''))
  await expect(phone.getByRole('heading', { level: 1 })).toContainText('Priya')
  await expect(phone.getByText("Helping with Maria's care")).toBeVisible()
  await phone.close()
})
