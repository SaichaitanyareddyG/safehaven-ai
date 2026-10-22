import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { AppointmentCard, CurrentStayCard } from '@/features/patient-app/MyCards'
import { useMyAppointments, useMyProfile, useMyVisits } from '@/features/patient-app/use-my-data'
import { formatDate } from '@/lib/format'
import { useNow } from '@/lib/use-now'

export function MyVisitsPage() {
  const visits = useMyVisits()
  const profile = useMyProfile()
  const appointments = useMyAppointments()
  const now = useNow()
  const comingUp = (appointments.data?.results ?? []).filter((a) => new Date(a.starts_at).getTime() >= now - 60 * 60 * 1000)
  const admitted = profile.data?.admission_status === 'ACTIVE'
  const open = admitted ? (visits.data?.visits.filter((v) => v.status === 'OPEN') ?? []) : []
  const past = visits.data?.visits.filter((v) => !open.includes(v)) ?? []

  return (
    <MyAppLayout title="My visits" subtitle="Appointments and hospital stays">
      {comingUp.length > 0 && (
        <>
          <MySectionTitle>Coming up</MySectionTitle>
          {comingUp.map((a) => (
            <AppointmentCard key={a.id} appointment={a} />
          ))}
        </>
      )}
      {visits.isLoading && <MyLoading />}
      {visits.isError && <MyLoadError />}
      {visits.data && (
        <>
          {open.map((visit) => (
            <CurrentStayCard key={visit.id} visit={visit} room={profile.data?.room_number ?? null} />
          ))}
          {visits.data.visits.length === 0 && comingUp.length === 0 && (
            <MyCard>
              <p className="text-lg text-[#53656E]">No appointments or visits yet.</p>
            </MyCard>
          )}
          {past.length > 0 && (
            <>
              <MySectionTitle>Past visits</MySectionTitle>
              <MyCard className="py-1">
                {past.map((visit) => (
                  <div
                    key={visit.id}
                    className="flex flex-wrap items-baseline justify-between gap-2 border-b border-[#E1E8EC] py-3 last:border-b-0"
                  >
                    <span className="text-base">{visit.reason_for_visit ?? 'Hospital visit'}</span>
                    <span className="text-sm text-[#53656E]">
                      {formatDate(visit.admission_date)}
                      {visit.discharge_date ? ` – ${formatDate(visit.discharge_date)}` : ''}
                    </span>
                  </div>
                ))}
              </MyCard>
            </>
          )}
        </>
      )}
    </MyAppLayout>
  )
}
