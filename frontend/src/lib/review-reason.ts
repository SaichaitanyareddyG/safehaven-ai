/**
 * The backend stores why an instruction needs review as a code plus the
 * technical detail ("FACT_PRESERVATION_FAILED: timing changed from …"). That
 * is for the record; a nurse needs to know what happened and what to do.
 */
export interface ReviewReasonText {
  title: string
  body: string
  /** The AI's own output was the problem: offer "Try again", not a rewrite. */
  aiProblem: boolean
}

export function describeReviewReason(reason: string): ReviewReasonText {
  if (reason.startsWith('FACT_PRESERVATION_FAILED')) {
    return {
      title: 'SafeHaven stopped its own patient text',
      body:
        "The AI's patient-friendly version didn't match your instruction exactly, so it was not shown to anyone. " +
        'This is usually just the AI wording things differently — press Try again. The differences it found are listed below.',
      aiProblem: true,
    }
  }
  if (reason.startsWith('AI_GENERATION_FAILED')) {
    return {
      title: "The AI couldn't write the patient text",
      body: 'The AI service had a problem. Nothing was shown to the patient — press Try again.',
      aiProblem: true,
    }
  }
  if (reason.startsWith('AI_EXTRACTION_FAILED')) {
    return {
      title: "The AI couldn't read this instruction",
      body: 'Check the wording below and submit it again. Nothing was shown to the patient.',
      aiProblem: false,
    }
  }
  // Missing or unclear details: the facts card below lists each one with
  // what it means, so the banner doesn't repeat the backend's wording.
  return {
    title: 'A detail is missing or unclear',
    body: 'Check the highlighted details below, then add them to the instruction and submit it again.',
    aiProblem: false,
  }
}

/** One short line, for lists. */
export function shortReviewReason(reason: string): string {
  if (reason.startsWith('FACT_PRESERVATION_FAILED')) return 'AI text blocked — try again'
  if (reason.startsWith('AI_GENERATION_FAILED')) return 'AI service problem — try again'
  if (reason.startsWith('AI_EXTRACTION_FAILED')) return "AI couldn't read it"
  return 'A detail is missing — add it'
}
