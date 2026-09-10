// These lists mirror the real backend pipeline stages (see
// backend/app/instructions/service.py: _run_analysis_and_apply /
// _run_generation_and_apply) — not decorative placeholder text. Update them
// together if the pipeline itself changes.

export const ANALYZE_STEPS = [
  'Sending instruction text to AI',
  'Extracting structured facts (medication, dose, route, frequency…)',
  'Normalizing values (abbreviations, units)',
  'Checking for ambiguous or conflicting facts',
  'Checking all required fields are present',
  'Finalizing status',
]

export const GENERATE_STEPS = [
  'Generating patient-friendly text',
  'Checking the dose number was preserved',
  'Checking safety warnings were preserved',
  'Re-extracting facts from the generated text',
  'Comparing re-extracted facts to the original',
  'Checking for any unsupported facts added',
  'Finalizing safety verdict',
]

export const TRANSLATE_STEPS = [
  'Translating into the patient’s preferred language',
  'Back-translating to English to verify meaning',
  'Re-extracting facts from the back-translation',
  'Comparing back-translated facts to the original',
  'Finalizing translation safety verdict',
]
