import { expect, test } from '@playwright/test'

import { bookAppointment, discharge, linkPath, newPatientWithApp, newStaff } from './helpers'

const BID = 'Take Metoprolol 25 mg orally twice daily with food.'
const PRN = 'Take Paracetamol 500 mg orally every 6 hours as needed for pain.'

test('invite link signs in once; medicines show their dose times', async ({ page, context }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, [BID, PRN])

  await page.goto(linkPath(patient.inviteLink))
  await expect(page).toHaveURL(/\/my$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Maria')

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Medicines' }).click()
  const cards = page.getByTestId('my-medicine-card')
  await expect(cards).toHaveCount(2)
  await expect(page.getByTestId('my-medicine-schedule').filter({ hasText: '8:00 AM, 8:00 PM' })).toBeVisible()
  await expect(page.getByTestId('my-medicine-schedule').filter({ hasText: 'Only when needed' })).toBeVisible()

  // The link is spent: a second use asks for a new one.
  const other = await context.newPage()
  await other.goto(linkPath(patient.inviteLink))
  await expect(other.getByRole('alert')).toContainText('expired or was already used')
})

test('at home: Taken, Skip and Undo are saved', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, [BID])
  await discharge(staff.token, patient.id)

  await page.goto(linkPath(patient.inviteLink))
  await expect(page.getByTestId('my-dose')).toHaveCount(2)
  await expect(page.getByTestId('my-doses-summary')).toHaveText('2 of 2 still to take.')

  await page.getByTestId('my-dose-taken').first().click()
  await page.getByTestId('my-dose-skip').first().click()
  await expect(page.getByTestId('my-doses-summary')).toHaveText('All done for today.')

  await page.reload()
  await expect(page.getByTestId('my-doses-summary')).toHaveText('All done for today.')
  await page.getByTestId('my-dose-undo').first().click()
  await expect(page.getByTestId('my-doses-summary')).toHaveText('1 of 2 still to take.')
})

test('ask a question and see the next appointment', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, [BID])
  await bookAppointment(staff.token, patient.id, new Date(Date.now() + 3 * 86400000))

  await page.goto(linkPath(patient.inviteLink))
  await expect(page.getByTestId('my-appointment')).toContainText('Cardiology check-up')

  await page.getByTestId('my-ask-link').click()
  await page.getByTestId('patient-chat-input').fill('When do I take Metoprolol?')
  await page.getByTestId('patient-chat-send').click()
  await expect(page.getByTestId('patient-chat-bubble')).toHaveCount(2)
})

test('sign out leaves nothing behind', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token)
  await page.goto(linkPath(patient.inviteLink))
  await page.getByTestId('my-sign-out').click()
  await expect(page).toHaveURL(/\/my\/sign-in$/)
  expect(await page.evaluate(() => localStorage.getItem('safehaven.patient_token'))).toBeNull()
  await page.goto('/my')
  await expect(page).toHaveURL(/\/my\/sign-in$/)
})
