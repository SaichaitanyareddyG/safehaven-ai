export type ReportCategory = 'LAB' | 'IMAGING' | 'DISCHARGE_SUMMARY' | 'LETTER' | 'OTHER'

export interface PatientReport {
  id: string
  title: string
  category: ReportCategory
  report_date: string | null
  content_type: string
  size: number
  shared_with_patient: boolean
  created_at: string
}

export const REPORT_CATEGORY_LABEL: Record<ReportCategory, string> = {
  LAB: 'Lab result',
  IMAGING: 'Imaging',
  DISCHARGE_SUMMARY: 'Discharge summary',
  LETTER: 'Letter',
  OTHER: 'Other',
}
