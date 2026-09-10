export type ComprehensionResponse = 'UNDERSTOOD' | 'HAS_QUESTION' | 'ASK_CARE_TEAM'

export interface ComprehensionFeedbackRead {
  care_instruction_id: string
  response: ComprehensionResponse
  created_at: string
}
