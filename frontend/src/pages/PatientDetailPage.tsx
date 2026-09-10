import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, LogOut } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { getPatient, updatePatient } from '@/api/patients'
import { AppLayout } from '@/components/AppLayout'
import { AdmissionStatusBadge } from '@/components/StatusBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ActivityTimeline } from '@/features/audit/ActivityTimeline'
import { CreateInstructionDialog } from '@/features/instructions/CreateInstructionDialog'
import { InstructionList } from '@/features/instructions/InstructionList'
import { PatientChatTranscript } from '@/features/patient-chat/PatientChatTranscript'
import { CreateCareLinkDialog } from '@/features/patients/CreateCareLinkDialog'
import { EncountersPanel } from '@/features/patients/EncountersPanel'
import { PatientConditionsPanel } from '@/features/patients/PatientConditionsPanel'
import { ApiError } from '@/lib/api-client'

export function PatientDetailPage() {
  const { patientId } = useParams<{ patientId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const {
    data: patient,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['patient', patientId],
    queryFn: () => getPatient(patientId!),
    enabled: !!patientId,
  })

  const dischargeMutation = useMutation({
    mutationFn: () => updatePatient(patientId!, { admission_status: 'DISCHARGED' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['patient', patientId] })
      queryClient.invalidateQueries({ queryKey: ['patients'] })
      // Discharge auto-revokes care-access tokens and adds new audit events —
      // both are shown on this same page, on a tab a clinician may already be
      // viewing (see InstructionActions.tsx's own note on this same pattern).
      queryClient.invalidateQueries({ queryKey: ['patient-audit', patientId] })
      queryClient.invalidateQueries({ queryKey: ['care-access-tokens', patientId] })
      toast.success('Patient discharged')
    },
    onError: (error) => {
      toast.error(error instanceof ApiError ? error.message : 'Failed to discharge patient')
    },
  })

  if (isLoading) {
    return (
      <AppLayout>
        <Skeleton className="h-32 w-full" />
      </AppLayout>
    )
  }

  if (isError || !patient) {
    return (
      <AppLayout>
        <p className="text-sm text-destructive">Failed to load patient.</p>
      </AppLayout>
    )
  }

  return (
    <AppLayout>
      <Button variant="ghost" size="sm" className="mb-4 -ml-2" onClick={() => navigate('/patients')}>
        <ArrowLeft className="h-4 w-4" />
        All patients
      </Button>

      <Card className="mb-6">
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="text-xl">
              {patient.first_name} {patient.last_name}
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">{patient.patient_code}</p>
          </div>
          <div className="flex items-center gap-2">
            <AdmissionStatusBadge status={patient.admission_status} />
            <CreateCareLinkDialog patientId={patient.id} />
          </div>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Date of birth</dt>
              <dd className="font-medium">{patient.date_of_birth}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Room</dt>
              <dd className="font-medium">{patient.room_number ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Preferred language</dt>
              <dd className="font-medium">{patient.preferred_language}</dd>
            </div>
            <div className="flex items-end">
              {patient.admission_status === 'ACTIVE' && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={dischargeMutation.isPending}
                  onClick={() => dischargeMutation.mutate()}
                  data-testid="discharge-button"
                >
                  <LogOut className="h-4 w-4" />
                  Discharge
                </Button>
              )}
            </div>
          </dl>
          <div className="mt-6 border-t pt-4">
            <PatientConditionsPanel patientId={patient.id} />
          </div>
          <div className="mt-6 border-t pt-4">
            <EncountersPanel patientId={patient.id} />
          </div>
        </CardContent>
      </Card>

      <Tabs defaultValue="instructions">
        <TabsList>
          <TabsTrigger value="instructions" data-testid="patient-tab-instructions">
            Instructions
          </TabsTrigger>
          <TabsTrigger value="activity" data-testid="patient-tab-activity">
            Activity &amp; Safety Timeline
          </TabsTrigger>
          <TabsTrigger value="chat" data-testid="patient-tab-chat">
            Patient Chat
          </TabsTrigger>
        </TabsList>
        <TabsContent value="instructions" data-testid="patient-tab-panel-instructions">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold tracking-tight">Instructions</h2>
            {patient.admission_status === 'ACTIVE' ? (
              <CreateInstructionDialog patientId={patient.id} />
            ) : (
              <p className="text-xs text-muted-foreground">Discharged patients cannot receive new instructions.</p>
            )}
          </div>
          <InstructionList patientId={patient.id} />
        </TabsContent>
        <TabsContent value="activity" data-testid="patient-tab-panel-activity">
          <h2 className="mb-4 text-lg font-semibold tracking-tight">Activity &amp; Safety Timeline</h2>
          <ActivityTimeline patientId={patient.id} />
        </TabsContent>
        <TabsContent value="chat" data-testid="patient-tab-panel-chat">
          <h2 className="mb-4 text-lg font-semibold tracking-tight">Patient Chat</h2>
          <PatientChatTranscript patientId={patient.id} />
        </TabsContent>
      </Tabs>
    </AppLayout>
  )
}
