import { expect, test } from '@playwright/test'

import { bookAppointment, discharge, linkPath, newPatientWithApp, newStaff, openInvite, PATIENT_PASSWORD } from './helpers'

const BID = 'Take Metoprolol 25 mg orally twice daily with food.'
const PRN = 'Take Paracetamol 500 mg orally every 6 hours as needed for pain.'

test('invite creates a password; reminders asked once; email + password sign-in', async ({ page, context }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, [BID, PRN])

  await openInvite(page, patient.inviteLink, { keepReminderPrompt: true })
  await expect(page.getByTestId('my-reminders-prompt')).toBeVisible()
  await expect(page.getByTestId('my-calendar-google')).toHaveAttribute('href', /calendar\.google\.com.*webcal/)
  await page.getByTestId('my-reminders-not-now').click()
  await expect(page.getByTestId('my-reminders-prompt')).toBeHidden()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Maria')

  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Medicines' }).click()
  const cards = page.getByTestId('my-medicine-card')
  await expect(cards).toHaveCount(2)
  await expect(page.getByTestId('my-medicine-schedule').filter({ hasText: '8:00 AM' }).filter({ hasText: '8:00 PM' })).toBeVisible()
  await expect(page.getByTestId('my-medicine-schedule').filter({ hasText: 'Only when needed' })).toBeVisible()

  // The link is spent: a second use says so and offers sign-in.
  const other = await context.newPage()
  await other.goto(linkPath(patient.inviteLink))
  await expect(other.getByRole('alert')).toContainText('already used or has expired')

  // Sign out, then back in with email + password; not asked about reminders again.
  await page.getByTestId('my-sign-out').click()
  await page.getByTestId('my-email').fill(patient.email)
  await page.getByTestId('my-password').fill('wrong-password')
  await page.getByTestId('my-sign-in').click()
  await expect(page.getByRole('alert')).toContainText("don't match")
  await page.getByTestId('my-password').fill(PATIENT_PASSWORD)
  await page.getByTestId('my-sign-in').click()
  await expect(page).toHaveURL(/\/my$/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Maria')
  await expect(page.getByTestId('my-reminders-prompt')).toHaveCount(0)
})

test('at home: Taken, Skip and Undo are saved', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token, [BID])
  await discharge(staff.token, patient.id)

  await openInvite(page, patient.inviteLink)
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

  await openInvite(page, patient.inviteLink)
  await expect(page.getByTestId('my-appointment')).toContainText('Cardiology check-up')

  await page.getByTestId('my-ask-link').click()
  await page.getByTestId('patient-chat-input').fill('When do I take Metoprolol?')
  await page.getByTestId('patient-chat-send').click()
  await expect(page.getByTestId('patient-chat-bubble')).toHaveCount(2)
})

test('sign out leaves nothing behind', async ({ page }) => {
  const staff = await newStaff()
  const patient = await newPatientWithApp(staff.token)
  await openInvite(page, patient.inviteLink)
  await page.getByTestId('my-sign-out').click()
  await expect(page).toHaveURL(/\/my\/sign-in$/)
  expect(await page.evaluate(() => localStorage.getItem('safehaven.patient_token'))).toBeNull()
  await page.goto('/my')
  await expect(page).toHaveURL(/\/my\/sign-in$/)
})
