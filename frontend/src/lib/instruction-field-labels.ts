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

/**
 * Plain-language help for the fields SafeHaven can ask a clinician to clarify:
 * what the word means, and how to add it to the instruction. Shown when a
 * nurse taps a "needs clarification" warning.
 */
export const FIELD_HELP: Record<string, { meaning: string; add: string }> = {
  medication_name: { meaning: 'Which medicine — brand or generic name.', add: 'e.g. "Take [medicine name] 500 mg…"' },
  dose_value: { meaning: 'How much in one dose, as a number.', add: 'e.g. "…500 mg…"' },
  dose_unit: { meaning: 'The unit of the dose: mg, mL, tablets, puffs…', add: 'e.g. "…250 mg…" or "…2 tablets…"' },
  route: {
    meaning: 'How the medicine goes into the body: by mouth (oral), injection, inhaled, on the skin, eye or ear drops…',
    add: 'e.g. "Take [medicine] 10 mg by mouth…"',
  },
  frequency: { meaning: 'How often: once daily, twice daily, every 6 hours, morning and evening…', add: 'e.g. "…twice daily…"' },
  timing: { meaning: 'When in the day, or in relation to meals or sleep.', add: 'e.g. "…after breakfast and dinner…"' },
  duration: { meaning: 'How long to keep taking it.', add: 'e.g. "…for 5 days."' },
  with_food: { meaning: 'Whether to take it with food or on an empty stomach.', add: 'e.g. "…after food…"' },
  activity: { meaning: 'What the patient should do: walk, sit up, exercises…', add: 'e.g. "Walk in the corridor…"' },
  assistance_required: { meaning: 'Whether someone must help or stay with them.', add: 'e.g. "…with a nurse beside you."' },
  allowed_intake: { meaning: 'What the patient may eat or drink.', add: 'e.g. "Clear fluids only…"' },
  restricted_intake: { meaning: 'What the patient must not eat or drink.', add: 'e.g. "…no salt added."' },
  body_site: { meaning: 'Where on the body the wound is.', add: 'e.g. "…the wound on your left knee…"' },
  action: { meaning: 'What to do to the wound.', add: 'e.g. "Change the dressing…"' },
  supplies: { meaning: 'What is needed to do it.', add: 'e.g. "…using sterile gauze."' },
  provider_or_specialty: { meaning: 'Who to see.', add: 'e.g. "See the cardiology clinic…"' },
  timeframe: { meaning: 'When the visit should happen.', add: 'e.g. "…in 2 weeks."' },
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

/** "frequency" -> "Frequency", for any instruction type. */
export function fieldLabel(key: string): string {
  for (const fields of Object.values(FIELD_LABELS_BY_TYPE)) {
    const hit = fields.find(([k]) => k === key)
    if (hit) return hit[1]
  }
  return key.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
}
