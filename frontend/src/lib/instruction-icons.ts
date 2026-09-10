import type { InstructionType } from '@/types/instructions'

export const INSTRUCTION_ICON: Record<InstructionType, string> = {
  MEDICATION: '💊',
  MOBILITY: '🚶',
  DIET: '🍽️',
  WOUND_CARE: '🩹',
  FOLLOW_UP: '📅',
  GENERAL: '📋',
}

export function instructionIcon(type: InstructionType | null): string {
  return type ? INSTRUCTION_ICON[type] : '📋'
}

export const INSTRUCTION_TYPE_LABEL: Record<InstructionType, string> = {
  MEDICATION: 'Medication',
  MOBILITY: 'Mobility',
  DIET: 'Diet',
  WOUND_CARE: 'Wound Care',
  FOLLOW_UP: 'Follow-up',
  GENERAL: 'Care Instruction',
}

export function instructionTypeLabel(type: InstructionType | null): string {
  return type ? INSTRUCTION_TYPE_LABEL[type] : 'Care Instruction'
}
