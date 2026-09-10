import { apiRequest } from '@/lib/api-client'
import type { ChatMessageListResponse, ChatSendResponse } from '@/types/patient-chat'

// Public, token-gated — same pattern as getCarePlan (see patient-access.ts).
export function getCarePlanChat(token: string): Promise<ChatMessageListResponse> {
  return apiRequest<ChatMessageListResponse>('/care-plan/chat', { params: { token }, skipAuth: true })
}

export function sendCarePlanChatMessage(token: string, text: string): Promise<ChatSendResponse> {
  return apiRequest<ChatSendResponse>('/care-plan/chat', {
    method: 'POST',
    body: { token, text },
    skipAuth: true,
  })
}

// Clinician-authenticated — the same transcript, read-only.
export function getPatientChat(patientId: string): Promise<ChatMessageListResponse> {
  return apiRequest<ChatMessageListResponse>(`/patients/${patientId}/chat`)
}
