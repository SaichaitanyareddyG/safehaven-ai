// These lists mirror the real backend pipeline stages (see
// backend/app/instructions/service.py: _run_analysis_and_apply /
// _run_generation_and_apply) — not decorative placeholder text. Update them
// together if the pipeline itself changes.

export const ANALYZE_STEPS = [
  'Reading your instruction',
  'Finding the medicine, dose, route and timing',
  'Spelling out abbreviations and units',
  'Checking nothing is unclear',
  'Checking nothing is missing',
  'Done',
]

export const GENERATE_STEPS = [
  'Writing it in plain language',
  'Checking the dose number was preserved',
  'Checking safety warnings were preserved',
  'Reading the plain version back',
  'Comparing it with your instruction',
  'Checking nothing was added',
  'Final safety check',
]

export const TRANSLATE_STEPS = [
  'Translating into the patient’s preferred language',
  'Back-translating to English to verify meaning',
  'Re-extracting facts from the back-translation',
  'Comparing back-translated facts to the original',
  'Finalizing translation safety verdict',
]
