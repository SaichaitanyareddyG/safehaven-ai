import { Navigate, useNavigate } from 'react-router-dom'

import { CarePlanDocument } from '@/features/care-plan/CarePlanDocument'
import { MyLoading } from '@/features/patient-app/MyAppLayout'
import { useMyAppointments, useMyCarePlan, useMyProfile } from '@/features/patient-app/use-my-data'
import { getPatientToken } from '@/lib/auth-storage'
import { useNow } from '@/lib/use-now'

/** Patient app: my care plan to print or save as PDF. */
export function MyPrintPage() {
  const navigate = useNavigate()
  const profile = useMyProfile()
  const plan = useMyCarePlan()
  const appointments = useMyAppointments()
  const now = useNow()
  if (!getPatientToken()) return <Navigate to="/my/sign-in" replace />
  if (!profile.data || !plan.data || !appointments.data) return <MyLoading />
  return (
    <CarePlanDocument
      patientName={`${profile.data.first_name} ${profile.data.last_name}`}
      plan={plan.data}
      appointments={appointments.data.results.filter((a) => new Date(a.starts_at).getTime() >= now)}
      printedAt={new Date(now)}
      onBack={() => navigate('/my/care')}
    />
  )
}
