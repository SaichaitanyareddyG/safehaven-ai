import { ApiError, apiRequest } from '@/lib/api-client'
import { getPatientToken, getToken } from '@/lib/auth-storage'
import type { PatientReport, ReportCategory } from '@/types/reports'

const API = import.meta.env.VITE_API_BASE_URL

export function listReports(patientId: string): Promise<{ results: PatientReport[] }> {
  return apiRequest<{ results: PatientReport[] }>(`/patients/${patientId}/reports`)
}

/** Multipart, so not through apiRequest (which sends JSON). */
export async function uploadReport(
  patientId: string,
  input: { file: File; title: string; category: ReportCategory; reportDate: string | null; share: boolean },
): Promise<PatientReport> {
  const form = new FormData()
  form.append('file', input.file)
  form.append('title', input.title)
  form.append('category', input.category)
  if (input.reportDate) form.append('report_date', input.reportDate)
  form.append('shared_with_patient', input.share ? 'true' : 'false')
  const response = await fetch(new URL(`/patients/${patientId}/reports`, API), {
    method: 'POST',
    headers: { Authorization: `Bearer ${getToken() ?? ''}` },
    body: form,
  })
  if (!response.ok) {
    let message = 'Could not upload the report'
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // keep the plain message
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as PatientReport
}

export function updateReport(
  reportId: string,
  payload: Partial<Pick<PatientReport, 'title' | 'category' | 'report_date' | 'shared_with_patient'>>,
): Promise<PatientReport> {
  return apiRequest<PatientReport>(`/reports/${reportId}`, { method: 'PATCH', body: payload })
}

export function removeReport(reportId: string): Promise<void> {
  return apiRequest<void>(`/reports/${reportId}`, { method: 'DELETE' })
}

/** Fetches the document with the right sign-in and opens it in a new tab.
 *  The tab is opened first (a browser only allows that straight from a
 *  tap), then pointed at the file once it has arrived. */
export async function openReport(path: string, asPatient = false): Promise<void> {
  const tab = window.open('', '_blank')
  try {
    const token = asPatient ? getPatientToken() : getToken()
    const response = await fetch(new URL(path, API), { headers: { Authorization: `Bearer ${token ?? ''}` } })
    if (!response.ok) throw new ApiError(response.status, 'This report is not available')
    const url = URL.createObjectURL(await response.blob())
    if (tab) tab.location.href = url
    else window.location.href = url
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    tab?.close()
    throw error
  }
}
