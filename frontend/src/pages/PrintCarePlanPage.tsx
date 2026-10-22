import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'

import { getCarePlanPrintout } from '@/api/patients'
import { CarePlanDocument } from '@/features/care-plan/CarePlanDocument'

/** Staff: the patient's care plan to print or save as PDF (e.g. at discharge). */
export function PrintCarePlanPage() {
  const { patientId } = useParams<{ patientId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['care-plan-printout', patientId],
    queryFn: () => getCarePlanPrintout(patientId!),
    enabled: !!patientId,
    staleTime: 0,
  })
  if (isLoading) return <p className="p-8 text-center text-muted-foreground">Preparing the care plan…</p>
  if (isError || !data) return <p className="p-8 text-center text-destructive">Could not load the care plan.</p>
  return (
    <CarePlanDocument
      patientName={`${data.patient_first_name} ${data.patient_last_name}`}
      dateOfBirth={data.date_of_birth}
      patientCode={data.patient_code}
      plan={data.care_plan}
      appointments={data.appointments}
      printedAt={new Date(data.printed_at)}
      onBack={() => navigate(`/patients/${patientId}`)}
    />
  )
}
