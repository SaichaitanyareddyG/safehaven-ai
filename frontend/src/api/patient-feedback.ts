import { apiRequest } from '@/lib/api-client'
import type { ComprehensionFeedbackRead, ComprehensionResponse, TeachBackResult } from '@/types/patient-feedback'

// Public, token-gated — same pattern as getCarePlan (see patient-access.ts).
export function sendComprehensionFeedback(
  token: string,
  instructionId: string,
  response: ComprehensionResponse,
): Promise<ComprehensionFeedbackRead> {
  return apiRequest<ComprehensionFeedbackRead>('/care-plan/feedback', {
    method: 'POST',
    body: { token, instruction_id: instructionId, response },
    skipAuth: true,
  })
}

export function sendTeachBack(token: string, instructionId: string, responseText: string): Promise<TeachBackResult> {
  return apiRequest<TeachBackResult>('/care-plan/teach-back', {
    method: 'POST',
    body: { token, instruction_id: instructionId, response_text: responseText },
    skipAuth: true,
  })
}
