import { apiRequest } from '@/lib/api-client'
import type {
  CareInstructionDetail,
  CareInstructionListResponse,
  CareInstructionRead,
  ClinicalStatus,
  InstructionStatus,
  TranslationResultItem,
} from '@/types/instructions'
import type { Language } from '@/types/patients'

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

export function createInstruction(patientId: string, text: string): Promise<CareInstructionRead> {
  return apiRequest<CareInstructionRead>(`/patients/${patientId}/instructions`, {
    method: 'POST',
    body: { text },
  })
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
