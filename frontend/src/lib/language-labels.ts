import type { Language } from '@/types/patients'

// Native-script labels for the patient-facing language selector — a patient
// choosing their language shouldn't have to read English to find it.
export const LANGUAGE_NATIVE_LABEL: Record<Language, string> = {
  ENGLISH: 'English',
  TELUGU: 'తెలుగు',
  HINDI: 'हिंदी',
}

export const ALL_LANGUAGES: Language[] = ['ENGLISH', 'TELUGU', 'HINDI']
