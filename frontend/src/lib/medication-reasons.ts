/**
 * Why a medication scan was blocked or needs review, in nurse language. The
 * backend sends stable codes (mismatch_reasons); these are the words.
 */
const REASON_TEXT: Record<string, string> = {
  PRODUCT_NOT_FOUND: "Barcode not recognised — check the product, or photograph the label instead.",
  NO_MATCHING_ORDER: 'There is no active order for this medicine for this patient.',
  MULTIPLE_ACTIVE_ORDERS: 'More than one active order matches — check which one applies.',
  STOPPED_ORDER_SCANNED: 'This medicine has been stopped for this patient.',
  ALLERGY_ALERT: 'The patient has a documented allergy to this medicine.',
  PATIENT_NIL_BY_MOUTH: 'The patient is nil by mouth.',
  PATIENT_NOT_ADMITTED: 'The patient is not currently admitted.',
  DOSE_MISMATCH: "The product's strength doesn't match the ordered dose.",
  ROUTE_MISMATCH: "The product's route doesn't match the order.",
  FORMULATION_MISMATCH: "The product's form (for example extended-release) doesn't match the order.",
  FORMULATION_UNSPECIFIED: "The order doesn't say which form to give — confirm before giving.",
  TIME_OUTSIDE_WINDOW: 'It is outside the scheduled time window for this dose.',
  SEVERE_DRUG_INTERACTION: "Serious interaction with another of the patient's medicines.",
  MODERATE_DRUG_INTERACTION: "Possible interaction with another of the patient's medicines.",
}

export function mismatchReasonText(code: string): string {
  return REASON_TEXT[code] ?? code.replace(/_/g, ' ').toLowerCase().replace(/^./, (c) => c.toUpperCase())
}
