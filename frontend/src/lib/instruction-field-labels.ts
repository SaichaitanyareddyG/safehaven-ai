import type { InstructionType } from '@/types/instructions'

export const FIELD_LABELS_BY_TYPE: Record<InstructionType, [key: string, label: string][]> = {
  MEDICATION: [
    ['medication_name', 'Medication'],
    ['dose_value', 'Dose'],
    ['dose_unit', 'Dose unit'],
    ['route', 'Route'],
    ['frequency', 'Frequency'],
    ['timing', 'Timing'],
    ['duration', 'Course length'],
    ['with_food', 'With food'],
    ['reason', 'Reason (if stated)'],
    ['warnings', 'Warnings'],
  ],
  MOBILITY: [
    ['activity', 'Activity'],
    ['timing', 'Timing'],
    ['duration', 'Duration'],
    ['assistance_required', 'Assistance required'],
    ['reason', 'Reason (if stated)'],
    ['restrictions', 'Restrictions'],
  ],
  DIET: [
    ['allowed_intake', 'Allowed intake'],
    ['restricted_intake', 'Restricted intake'],
    ['timing', 'Timing'],
    ['special_restrictions', 'Special restrictions'],
    ['reason', 'Reason (if stated)'],
  ],
  WOUND_CARE: [
    ['body_site', 'Body site'],
    ['action', 'Action'],
    ['frequency', 'Frequency'],
    ['supplies', 'Supplies'],
    ['warning_signs', 'Warning signs'],
    ['reason', 'Reason (if stated)'],
  ],
  FOLLOW_UP: [
    ['provider_or_specialty', 'Provider / specialty'],
    ['timeframe', 'Timeframe'],
    ['purpose', 'Purpose'],
  ],
  GENERAL: [
    ['summary', 'Summary'],
    ['details', 'Details'],
  ],
}

export const INSTRUCTION_TYPE_LABEL: Record<InstructionType, string> = {
  MEDICATION: 'Medication',
  MOBILITY: 'Mobility',
  DIET: 'Diet',
  WOUND_CARE: 'Wound Care',
  FOLLOW_UP: 'Follow-up',
  GENERAL: 'General',
}

export function formatFactValue(value: unknown): string {
  if (value === null || value === undefined) return 'Not specified'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : 'Not specified'
  return String(value)
}
