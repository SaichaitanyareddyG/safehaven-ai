export type ChatRole = 'PATIENT' | 'ASSISTANT'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  emergency_flagged: boolean
  redirect_flagged: boolean
  web_search_used: boolean
  created_at: string
}

export interface ChatMessageListResponse {
  messages: ChatMessage[]
}

export interface ChatSendResponse {
  patient_message: ChatMessage
  assistant_message: ChatMessage
}
