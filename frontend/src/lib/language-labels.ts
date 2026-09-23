import type { Language } from '@/types/patients'

// Native-script labels for the patient-facing language selector — a patient
// choosing their language shouldn't have to read English to find it.
export const LANGUAGE_NATIVE_LABEL: Record<Language, string> = {
  ENGLISH: 'English',
  TELUGU: 'తెలుగు',
  HINDI: 'हिंदी',
  SPANISH: 'Español',
  MANDARIN: '中文',
  VIETNAMESE: 'Tiếng Việt',
  TAGALOG: 'Tagalog',
  ARABIC: 'العربية',
  KOREAN: '한국어',
  RUSSIAN: 'Русский',
  FRENCH: 'Français',
}

export const ALL_LANGUAGES: Language[] = [
  'ENGLISH',
  'SPANISH',
  'MANDARIN',
  'VIETNAMESE',
  'TAGALOG',
  'ARABIC',
  'KOREAN',
  'RUSSIAN',
  'FRENCH',
  'HINDI',
  'TELUGU',
]

// Right-to-left scripts need dir="rtl" or the text renders with punctuation
// and numbers in the wrong places — which for a medication instruction is not
// a cosmetic problem. Kept as a set so adding another RTL language (Hebrew,
// Urdu, Farsi) is a one-line change.
const RTL_LANGUAGES = new Set<Language>(['ARABIC'])

export function textDirection(language: Language): 'rtl' | 'ltr' {
  return RTL_LANGUAGES.has(language) ? 'rtl' : 'ltr'
}
