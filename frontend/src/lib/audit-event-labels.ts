import type { AuditEvent } from '@/types/audit'

export type AuditEventCategory = 'info' | 'safety-warning' | 'approval' | 'patient-activity'

const CATEGORY_BY_EVENT_TYPE: Record<string, AuditEventCategory> = {
  INSTRUCTION_NEEDS_REVIEW: 'safety-warning',
  FACT_VALIDATION_FAILED: 'safety-warning',
  TRANSLATION_VALIDATION_FAILED: 'safety-warning',
  INSTRUCTION_REJECTED: 'safety-warning',
  INSTRUCTION_APPROVED: 'approval',
  CARE_PLAN_VIEWED: 'patient-activity',
  PATIENT_CHAT_EMERGENCY_FLAGGED: 'safety-warning',
  PATIENT_CHAT_TREATMENT_CHANGE_REDIRECTED: 'safety-warning',
  PATIENT_CHAT_WEB_SEARCH_USED: 'patient-activity',
  PATIENT_COMPREHENSION_NEEDS_ATTENTION: 'safety-warning',
  PATIENT_TEACH_BACK_NEEDS_ATTENTION: 'safety-warning',
  LOGIN_FAILED: 'safety-warning',
  PATIENT_ALLERGY_ADDED: 'safety-warning',
  // Module 2. MEDICATION_MISMATCH is the important one: it is what a BLOCKED
  // wrong-drug, allergy or interaction scan records. Without it here the
  // category fell through to 'info' and a caught medication error rendered as
  // a grey dot indistinguishable from "Clinician logged in".
  MEDICATION_MISMATCH: 'safety-warning',
  MEDICATION_SCAN_FAILED: 'safety-warning',
  MEDICATION_VERIFIED: 'approval',
  ADMINISTRATION_CONFIRMED: 'approval',
  ADMINISTRATION_NOT_GIVEN: 'safety-warning',
  // Module 3. Registration and enrolment are routine setup, so 'info'.
  // Revocation is not: it removes a patient-safety monitor's ability to report
  // anything at all, and a monitor going dark should never look like a login.
  WEARABLE_DEVICE_REVOKED: 'safety-warning',
}

export function auditEventCategory(eventType: string): AuditEventCategory {
  return CATEGORY_BY_EVENT_TYPE[eventType] ?? 'info'
}

function languageSuffix(event: AuditEvent): string {
  const language = event.event_metadata['language']
  return typeof language === 'string' ? ` (${language.charAt(0)}${language.slice(1).toLowerCase()})` : ''
}

function medicationSuffix(event: AuditEvent): string {
  const name = event.event_metadata['medication_name']
  return typeof name === 'string' && name ? `: ${name}` : ''
}

// Module 3. device_code is an asset tag (e.g. SH-WEAR-001), not patient data,
// so it is safe to render on the timeline.
function deviceSuffix(event: AuditEvent): string {
  const code = event.event_metadata['device_code']
  return typeof code === 'string' && code ? `: ${code}` : ''
}

function resultSuffix(event: AuditEvent): string {
  const result = event.event_metadata['result']
  const reasons = event.event_metadata['reasons']
  if (typeof result !== 'string') return ''
  const detail = Array.isArray(reasons) && reasons.length > 0 ? ` — ${reasons.join(', ').toLowerCase().replace(/_/g, ' ')}` : ''
  return ` (${result}${detail})`
}

export function auditEventDescription(event: AuditEvent): string {
  switch (event.event_type) {
    case 'LOGIN_FAILED':
      return 'Failed sign-in attempt'
    case 'INSTRUCTION_DICTATED':
      return 'Instruction dictated by voice'
    case 'MEDICATION_CLINICAL_STATUS_CHANGED':
      return `Medication status changed${
        typeof event.event_metadata['status'] === 'string' ? ` to ${event.event_metadata['status']}` : ''
      }`
    case 'PATIENT_ALLERGY_ADDED':
      return 'Allergy documented'
    case 'PATIENT_ALLERGY_REMOVED':
      return 'Allergy removed'
    case 'PATIENT_CONDITION_ADDED':
      return 'Condition documented'
    case 'PATIENT_CONDITION_REMOVED':
      return 'Condition removed'
    case 'ENCOUNTER_CREATED':
      return 'Encounter created'

    // --- Module 2: medication administration verification ---
    case 'PATIENT_SCANNED':
      return event.event_metadata['resolved'] === false
        ? 'Unrecognised patient wristband scanned'
        : 'Patient wristband scanned'
    case 'MEDICATION_SCANNED':
      return event.event_metadata['resolved'] === false
        ? 'Unrecognised medication barcode scanned'
        : 'Medication barcode scanned'
    case 'MEDICATION_VERIFIED':
      return `Medication verified at the bedside${resultSuffix(event)}`
    case 'MEDICATION_MISMATCH':
      return `Medication administration blocked${resultSuffix(event)}`
    case 'MEDICATION_SCAN_FAILED':
      return 'Barcode could not be read — label photo used instead'
    case 'MEDICATION_IMAGE_IDENTIFIED':
      return `Medication read from a label photo${medicationSuffix(event)}`
    case 'MEDICATION_MANUALLY_CONFIRMED':
      return `Medication identity confirmed by the nurse${medicationSuffix(event)}`
    case 'ADMINISTRATION_CONFIRMED':
      return 'Dose administered'
    case 'ADMINISTRATION_NOT_GIVEN':
      return `Dose not given${
        typeof event.event_metadata['reason'] === 'string'
          ? ` (${String(event.event_metadata['reason']).toLowerCase().replace(/_/g, ' ')})`
          : ''
      }`
    case 'USER_LOGIN':
      return 'Clinician logged in'
    case 'PATIENT_CREATED':
      return 'Patient record created'
    case 'PATIENT_UPDATED':
      return 'Patient record updated'
    case 'PATIENT_DISCHARGED':
      return 'Patient discharged'
    case 'INSTRUCTION_CREATED':
      return 'Care instruction created'
    case 'INSTRUCTION_ANALYSIS_STARTED':
      return 'AI analysis started'
    case 'INSTRUCTION_ANALYSIS_PASSED':
      return 'AI analysis passed — all required facts extracted'
    case 'INSTRUCTION_NEEDS_REVIEW':
      return event.event_metadata['reason'] === 'AI_EXTRACTION_FAILED'
        ? 'AI analysis failed — flagged for clinician review'
        : 'Flagged for clinician review — clarification needed'
    case 'CLARIFICATION_CREATED':
      return 'Clinician submitted a clarification'
    case 'PATIENT_OUTPUT_GENERATED':
      return 'Patient-friendly version generated by AI'
    case 'FACT_VALIDATION_PASSED':
      return 'Fact-preservation check passed'
    case 'FACT_VALIDATION_FAILED':
      return 'Fact-preservation check FAILED — blocked from patient view'
    case 'INSTRUCTION_APPROVED':
      return 'Instruction approved for patient viewing'
    case 'INSTRUCTION_REJECTED':
      return 'Instruction rejected by clinician'
    case 'TRANSLATION_CREATED':
      return `Translation generated${languageSuffix(event)}`
    case 'TRANSLATION_VALIDATION_PASSED':
      return `Translation safety check passed${languageSuffix(event)}`
    case 'TRANSLATION_VALIDATION_FAILED':
      return `Translation safety check FAILED${languageSuffix(event)} — blocked from patient view`
    case 'CARE_ACCESS_TOKEN_CREATED':
      return 'Patient care link created'
    case 'CARE_ACCESS_TOKEN_REVOKED':
      return event.event_metadata['reason'] === 'patient_discharged'
        ? 'Patient care link auto-revoked (discharge)'
        : 'Patient care link revoked'
    case 'CARE_PLAN_VIEWED':
      return 'Patient viewed their care plan'
    case 'PATIENT_CHAT_EMERGENCY_FLAGGED':
      return 'Patient chat: emergency response triggered'
    case 'PATIENT_CHAT_TREATMENT_CHANGE_REDIRECTED':
      return 'Patient chat: redirected to care team (treatment change)'
    case 'PATIENT_CHAT_WEB_SEARCH_USED':
      return 'Patient chat: answered using trusted medical web search'
    case 'PATIENT_COMPREHENSION_NEEDS_ATTENTION':
      return event.event_metadata['response'] === 'ASK_CARE_TEAM'
        ? 'Patient asked to be contacted by their care team'
        : 'Patient said they still have a question'
    case 'PATIENT_TEACH_BACK_NEEDS_ATTENTION':
      return "Patient's own explanation missed part of this instruction — teach-back flagged for review"
    case 'WEARABLE_DEVICE_REGISTERED':
      return event.event_metadata['reissued'] === true
        ? `Wearable enrolment code re-issued${deviceSuffix(event)}`
        : `Wearable device registered${deviceSuffix(event)}`
    case 'WEARABLE_DEVICE_ENROLLED':
      return `Wearable device enrolled and credentialled${deviceSuffix(event)}`
    case 'WEARABLE_DEVICE_REVOKED':
      return `Wearable device credential revoked${deviceSuffix(event)}`
    default:
      return event.event_type
  }
}
