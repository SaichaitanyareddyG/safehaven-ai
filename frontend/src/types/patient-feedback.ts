export type ComprehensionResponse = 'UNDERSTOOD' | 'HAS_QUESTION' | 'ASK_CARE_TEAM'

export interface ComprehensionFeedbackRead {
  care_instruction_id: string
  response: ComprehensionResponse
  created_at: string
}

export interface TeachBackResult {
  care_instruction_id: string
  passed: boolean
  confirmed_facts: string[]
  missing_facts: string[]
  created_at: string
}
