import { ApiError, apiRequest } from '@/lib/api-client'
import { clearToken, getToken } from '@/lib/auth-storage'
import type {
  CareInstructionDetail,
  CareInstructionListResponse,
  CareInstructionRead,
  ClinicalStatus,
  InstructionStatus,
  TranscriptionResponse,
  TranslationResultItem,
} from '@/types/instructions'
import type { Language } from '@/types/patients'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL

export interface ListInstructionsParams {
  status?: InstructionStatus
  clinical_status?: ClinicalStatus
  limit?: number
  offset?: number
}

export function listPatientInstructions(
  patientId: string,
  params: ListInstructionsParams = {},
): Promise<CareInstructionListResponse> {
  return apiRequest<CareInstructionListResponse>(`/patients/${patientId}/instructions`, { params })
}

export function createInstruction(
  patientId: string,
  text: string,
  dictated = false,
): Promise<CareInstructionRead> {
  return apiRequest<CareInstructionRead>(`/patients/${patientId}/instructions`, {
    method: 'POST',
    body: { text, dictated },
  })
}

// Multipart upload — apiRequest only handles JSON bodies, so this makes its
// own fetch call, matching identifyMedicationFromImage's pattern exactly.
//
// Returns an editable DRAFT and creates nothing server-side: the transcript
// only becomes an instruction when the clinician submits it through
// createInstruction above. See MODULE_1_VOICE_DICTATION_DESIGN.md §3.
export async function transcribeDictation(audio: Blob): Promise<TranscriptionResponse> {
  const formData = new FormData()
  formData.append('file', audio, 'dictation.webm')

  const authToken = getToken()
  const response = await fetch(new URL('/instructions/transcribe', API_BASE_URL), {
    method: 'POST',
    headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
    body: formData,
  })

  if (response.status === 401) {
    clearToken()
    window.location.assign('/login')
    throw new ApiError(401, 'Session expired')
  }
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText)
  }
  return response.json()
}

export function getInstruction(instructionId: string): Promise<CareInstructionDetail> {
  return apiRequest<CareInstructionDetail>(`/instructions/${instructionId}`)
}

export function analyzeInstruction(instructionId: string): Promise<CareInstructionDetail> {
  return apiRequest<CareInstructionDetail>(`/instructions/${instructionId}/analyze`, { method: 'POST' })
}

export function clarifyInstruction(instructionId: string, text: string): Promise<CareInstructionDetail> {
  return apiRequest<CareInstructionDetail>(`/instructions/${instructionId}/clarify`, {
    method: 'POST',
    body: { text },
  })
}

export function generatePatientOutput(instructionId: string): Promise<CareInstructionDetail> {
  return apiRequest<CareInstructionDetail>(`/instructions/${instructionId}/generate`, { method: 'POST' })
}

export function approveInstruction(instructionId: string): Promise<CareInstructionRead> {
  return apiRequest<CareInstructionRead>(`/instructions/${instructionId}/approve`, { method: 'POST' })
}

export function rejectInstruction(instructionId: string, reason: string): Promise<CareInstructionRead> {
  return apiRequest<CareInstructionRead>(`/instructions/${instructionId}/reject`, {
    method: 'POST',
    body: { reason },
  })
}

export function updateClinicalStatus(instructionId: string, newStatus: ClinicalStatus): Promise<CareInstructionRead> {
  return apiRequest<CareInstructionRead>(`/instructions/${instructionId}/clinical-status`, {
    method: 'PATCH',
    body: { status: newStatus },
  })
}

export function requestTranslations(
  instructionId: string,
  languages: Language[],
): Promise<Record<string, TranslationResultItem>> {
  return apiRequest<Record<string, TranslationResultItem>>(`/instructions/${instructionId}/translations`, {
    method: 'POST',
    body: { languages },
  })
}
