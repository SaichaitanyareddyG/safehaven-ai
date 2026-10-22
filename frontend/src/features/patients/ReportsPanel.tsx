import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, FileText, Trash2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { listReports, openReport, removeReport, updateReport, uploadReport } from '@/api/reports'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ApiError } from '@/lib/api-client'
import { formatDate } from '@/lib/format'
import { REPORT_CATEGORY_LABEL, type ReportCategory } from '@/types/reports'

function size(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** Lab results, scans, discharge summaries and letters for this patient.
 *  Hidden from the patient until shared; every opening is recorded. */
export function ReportsPanel({ patientId }: { patientId: string }) {
  const queryClient = useQueryClient()
  const { data } = useQuery({ queryKey: ['reports', patientId], queryFn: () => listReports(patientId) })
  const fileInput = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [category, setCategory] = useState<ReportCategory>('LAB')
  const [reportDate, setReportDate] = useState('')
  const [share, setShare] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)

  function refresh() {
    queryClient.invalidateQueries({ queryKey: ['reports', patientId] })
    queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
  }
  function reset() {
    setAdding(false)
    setFile(null)
    setTitle('')
    setCategory('LAB')
    setReportDate('')
    setShare(false)
  }

  const upload = useMutation({
    mutationFn: () => uploadReport(patientId, { file: file!, title: title.trim(), category, reportDate: reportDate || null, share }),
    onSuccess: (r) => {
      refresh()
      reset()
      toast.success(r.shared_with_patient ? 'Report uploaded and shared with the patient' : 'Report uploaded (not shared yet)')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not upload the report'),
  })
  const toggleShare = useMutation({
    mutationFn: ({ id, shared }: { id: string; shared: boolean }) => updateReport(id, { shared_with_patient: shared }),
    onSuccess: (r) => {
      refresh()
      toast.success(r.shared_with_patient ? 'Now visible in the patient app' : 'Hidden from the patient app')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not change sharing'),
  })
  const remove = useMutation({
    mutationFn: (id: string) => removeReport(id),
    onSuccess: () => {
      refresh()
      setConfirmRemove(null)
      toast.success('Report removed')
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : 'Could not remove the report'),
  })

  const reports = data?.results ?? []
  return (
    <div className="space-y-3" data-testid="reports-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium">Reports</p>
        {!adding && (
          <Button size="sm" variant="outline" onClick={() => setAdding(true)} data-testid="report-add">
            <Upload className="h-4 w-4" />
            Upload report
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        PDF or photo, up to 10 MB. The patient sees a report in their app only after you share it. Every opening is
        recorded.
      </p>

      {adding && (
        <div className="space-y-3 rounded-lg border border-dashed p-3">
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,image/png,image/jpeg"
            className="block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-primary/10 file:px-3 file:py-2 file:text-sm file:font-medium file:text-primary"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null
              setFile(f)
              if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ''))
            }}
            data-testid="report-file"
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="space-y-1">
              <Label htmlFor="report-title" className="text-xs">
                Title (the patient sees this)
              </Label>
              <Input id="report-title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Blood test" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="report-category" className="text-xs">
                Type
              </Label>
              <Select value={category} onValueChange={(v) => setCategory(v as ReportCategory)}>
                <SelectTrigger id="report-category" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(REPORT_CATEGORY_LABEL).map(([value, label]) => (
                    <SelectItem key={value} value={value}>
                      {label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="report-date" className="text-xs">
                Report date
              </Label>
              <Input id="report-date" type="date" value={reportDate} onChange={(e) => setReportDate(e.target.value)} />
            </div>
          </div>
          <label className="flex items-start gap-3 text-sm leading-snug">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
              checked={share}
              onChange={(e) => setShare(e.target.checked)}
              data-testid="report-share"
            />
            <span>Share with the patient now (they see it in their app)</span>
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={reset}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={!file || !title.trim() || upload.isPending}
              onClick={() => upload.mutate()}
              data-testid="report-upload"
            >
              {upload.isPending ? 'Uploading…' : 'Upload'}
            </Button>
          </div>
        </div>
      )}

      {reports.length === 0 && !adding && <p className="text-sm text-muted-foreground">No reports yet.</p>}
      <div className="space-y-2">
        {reports.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2" data-testid="report-row">
            <button
              type="button"
              className="flex min-w-0 items-center gap-2 text-left"
              onClick={() =>
                openReport(`/reports/${r.id}/file`).catch((e) =>
                  toast.error(e instanceof ApiError ? e.message : 'Could not open the report'),
                )
              }
            >
              <FileText className="h-5 w-5 shrink-0 text-primary" aria-hidden="true" />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium underline-offset-2 hover:underline">{r.title}</span>
                <span className="block text-xs text-muted-foreground">
                  {REPORT_CATEGORY_LABEL[r.category]}
                  {r.report_date && ` · ${formatDate(r.report_date)}`} · {size(r.size)}
                </span>
              </span>
            </button>
            <div className="flex items-center gap-1">
              <Badge variant="outline">{r.shared_with_patient ? 'Shared with patient' : 'Staff only'}</Badge>
              <Button
                variant="ghost"
                size="sm"
                disabled={toggleShare.isPending}
                onClick={() => toggleShare.mutate({ id: r.id, shared: !r.shared_with_patient })}
                aria-label={r.shared_with_patient ? `Hide ${r.title} from the patient` : `Share ${r.title} with the patient`}
              >
                {r.shared_with_patient ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {r.shared_with_patient ? 'Hide' : 'Share'}
              </Button>
              {confirmRemove === r.id ? (
                <Button variant="destructive" size="sm" disabled={remove.isPending} onClick={() => remove.mutate(r.id)}>
                  Confirm remove
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-destructive hover:text-destructive"
                  onClick={() => setConfirmRemove(r.id)}
                  aria-label={`Remove ${r.title}`}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
