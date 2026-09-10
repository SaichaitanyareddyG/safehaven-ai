import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { listPatients } from '@/api/patients'
import { AppLayout } from '@/components/AppLayout'
import { AdmissionStatusBadge } from '@/components/StatusBadge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { CreatePatientDialog } from '@/features/patients/CreatePatientDialog'
import type { AdmissionStatus } from '@/types/patients'
import { useDebouncedValue } from '@/lib/use-debounced-value'

export function PatientListPage() {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<AdmissionStatus | 'ALL'>('ACTIVE')
  const debouncedSearch = useDebouncedValue(search, 300)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['patients', { search: debouncedSearch, status }],
    queryFn: () =>
      listPatients({
        search: debouncedSearch || undefined,
        status: status === 'ALL' ? undefined : status,
        limit: 50,
      }),
  })

  return (
    <AppLayout>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Patients</h1>
          <p className="text-sm text-muted-foreground">Search, review, and register patients.</p>
        </div>
        <CreatePatientDialog />
      </div>

      <div className="mb-4 flex gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by name or patient code…"
            className="pl-8"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            data-testid="patient-search-input"
          />
        </div>
        <Select value={status} onValueChange={(value) => setStatus(value as AdmissionStatus | 'ALL')}>
          <SelectTrigger className="w-40" data-testid="patient-status-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ACTIVE">Active</SelectItem>
            <SelectItem value="DISCHARGED">Discharged</SelectItem>
            <SelectItem value="ALL">All patients</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="rounded-lg border bg-background">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Patient</TableHead>
              <TableHead>Code</TableHead>
              <TableHead>Date of birth</TableHead>
              <TableHead>Room</TableHead>
              <TableHead>Language</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  <TableCell colSpan={6}>
                    <Skeleton className="h-5 w-full" />
                  </TableCell>
                </TableRow>
              ))}
            {isError && (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-sm text-destructive">
                  Failed to load patients.
                </TableCell>
              </TableRow>
            )}
            {data && data.results.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                  No patients found.
                </TableCell>
              </TableRow>
            )}
            {data?.results.map((patient) => (
              <TableRow
                key={patient.id}
                className="cursor-pointer"
                onClick={() => navigate(`/patients/${patient.id}`)}
                data-testid="patient-row"
                data-patient-code={patient.patient_code}
              >
                <TableCell className="font-medium">
                  {patient.first_name} {patient.last_name}
                </TableCell>
                <TableCell className="text-muted-foreground">{patient.patient_code}</TableCell>
                <TableCell className="text-muted-foreground">{patient.date_of_birth}</TableCell>
                <TableCell className="text-muted-foreground">{patient.room_number ?? '—'}</TableCell>
                <TableCell className="text-muted-foreground">{patient.preferred_language}</TableCell>
                <TableCell>
                  <AdmissionStatusBadge status={patient.admission_status} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {data && (
        <p className="mt-3 text-xs text-muted-foreground">
          {data.total} patient{data.total === 1 ? '' : 's'}
        </p>
      )}
    </AppLayout>
  )
}
