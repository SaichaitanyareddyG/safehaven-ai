import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { AdmissionStatus } from '@/types/patients'
import type { CompletenessStatus, InstructionStatus, ValidationStatus } from '@/types/instructions'

const INSTRUCTION_STATUS_STYLES: Record<InstructionStatus, string> = {
  DRAFT: 'bg-muted text-muted-foreground border-border',
  PROCESSING: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-900',
  NEEDS_REVIEW:
    'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  READY_FOR_APPROVAL:
    'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950 dark:text-violet-300 dark:border-violet-900',
  APPROVED:
    'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
  REJECTED: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900',
}

const INSTRUCTION_STATUS_LABEL: Record<InstructionStatus, string> = {
  DRAFT: 'Draft',
  PROCESSING: 'Processing',
  NEEDS_REVIEW: 'Needs Review',
  READY_FOR_APPROVAL: 'Ready for Approval',
  APPROVED: 'Approved',
  REJECTED: 'Rejected',
}

export function InstructionStatusBadge({ status, className }: { status: InstructionStatus; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(INSTRUCTION_STATUS_STYLES[status], className)}
      data-testid="instruction-status-badge"
      data-status={status}
    >
      {INSTRUCTION_STATUS_LABEL[status]}
    </Badge>
  )
}

const ADMISSION_STATUS_STYLES: Record<AdmissionStatus, string> = {
  ACTIVE: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
  DISCHARGED: 'bg-muted text-muted-foreground border-border',
}

export function AdmissionStatusBadge({ status, className }: { status: AdmissionStatus; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(ADMISSION_STATUS_STYLES[status], className)}
      data-testid="admission-status-badge"
      data-status={status}
    >
      {status === 'ACTIVE' ? 'Active' : 'Discharged'}
    </Badge>
  )
}

const COMPLETENESS_STYLES: Record<CompletenessStatus, string> = {
  PASSED: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
  NEEDS_CLARIFICATION:
    'bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900',
  FAILED: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900',
}

const COMPLETENESS_LABEL: Record<CompletenessStatus, string> = {
  PASSED: 'Complete',
  NEEDS_CLARIFICATION: 'Needs Clarification',
  FAILED: 'Extraction Failed',
}

export function CompletenessBadge({ status, className }: { status: CompletenessStatus; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(COMPLETENESS_STYLES[status], className)}
      data-testid="completeness-badge"
      data-status={status}
    >
      {COMPLETENESS_LABEL[status]}
    </Badge>
  )
}

const VALIDATION_STYLES: Record<ValidationStatus, string> = {
  PENDING: 'bg-muted text-muted-foreground border-border',
  PASSED: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900',
  FAILED: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900',
}

export function ValidationStatusBadge({ status, className }: { status: ValidationStatus; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn(VALIDATION_STYLES[status], className)}
      data-testid="validation-status-badge"
      data-status={status}
    >
      {status === 'PASSED' ? 'Safe to show patient' : status === 'FAILED' ? 'Blocked — unsafe' : 'Pending'}
    </Badge>
  )
}
