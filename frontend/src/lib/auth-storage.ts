const TOKEN_KEY = 'safehaven.access_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// The patient app's session, kept apart from staff sign-in: a nurse signed in
// on the same browser and a patient's link never overwrite each other.
const PATIENT_TOKEN_KEY = 'safehaven.patient_token'

export function getPatientToken(): string | null {
  return localStorage.getItem(PATIENT_TOKEN_KEY)
}

export function setPatientToken(token: string): void {
  localStorage.setItem(PATIENT_TOKEN_KEY, token)
}

export function clearPatientToken(): void {
  localStorage.removeItem(PATIENT_TOKEN_KEY)
}
