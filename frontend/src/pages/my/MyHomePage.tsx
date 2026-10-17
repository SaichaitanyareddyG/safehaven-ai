import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { AllergiesCard, CurrentStayCard } from '@/features/patient-app/MyCards'
import { dosesToday, useMyCarePlan, useMyProfile, useMyVisits } from '@/features/patient-app/use-my-data'
import { formatDate } from '@/lib/format'

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

export function MyHomePage() {
  const profile = useMyProfile()
  const plan = useMyCarePlan()
  const visits = useMyVisits()

  const first = profile.data?.first_name
  const openVisit = visits.data?.visits.find((v) => v.status === 'OPEN')
  const medicines = plan.data?.instructions.filter((i) => i.instruction_type === 'MEDICATION') ?? []
  const otherCount = (plan.data?.instructions.length ?? 0) - medicines.length
  const doses = dosesToday(medicines)
  const stopped = plan.data?.past_medications.filter((m) => m.past_reason === 'STOPPED') ?? []

  return (
    <MyAppLayout title={first ? `${greeting()}, ${first}` : 'Today'} subtitle={subtitle(profile.data)}>
      {(profile.isLoading || plan.isLoading) && <MyLoading />}
      {(profile.isError || plan.isError) && <MyLoadError />}

      {plan.data && plan.data.allergies.length > 0 && <AllergiesCard allergies={plan.data.allergies} />}

      {openVisit && <CurrentStayCard visit={openVisit} room={profile.data?.room_number ?? null} />}

      {plan.data && (
        <>
          {doses.length > 0 && (
            <>
              <MySectionTitle>Your medicines today</MySectionTitle>
              {profile.data?.admission_status === 'ACTIVE' && (
                <p className="-mt-2 text-base text-[#53656E]">While you're in hospital, your nurse gives these.</p>
              )}
              <MyCard className="py-1" data-testid="my-doses-today">
                {doses.map((dose, i) => (
                  <div key={i} className="flex items-start gap-4 border-b border-[#E1E8EC] py-3 last:border-b-0">
                    <span className="min-w-[76px] text-lg font-semibold text-[#0F6383]">{dose.timeDisplay}</span>
                    <span className="flex flex-col">
                      <span className="text-lg font-semibold">
                        {dose.medicine.medication_name ?? 'Medicine'}
                        {dose.medicine.schedule?.dose ? ` ${dose.medicine.schedule.dose}` : ''}
                      </span>
                      {dose.medicine.schedule?.with_food && <span className="text-base text-[#53656E]">With food</span>}
                    </span>
                  </div>
                ))}
              </MyCard>
            </>
          )}

          <MySectionTitle>Your medicines</MySectionTitle>
          {medicines.length === 0 ? (
            <MyCard>
              <p className="text-lg text-[#53656E]">No medicines from your care team yet. They appear here once approved.</p>
            </MyCard>
          ) : (
            <Link to="/my/medicines" className="block" data-testid="my-home-medicines">
              <MyCard className="flex items-center justify-between gap-3 hover:bg-[#FAFCFC]">
                <div className="flex min-w-0 flex-col gap-1">
                  <span className="text-lg font-semibold">
                    {medicines.length} {medicines.length === 1 ? 'medicine' : 'medicines'} to take
                  </span>
                  <span className="truncate text-base text-[#53656E]">
                    {medicines.map((m) => m.medication_name ?? 'Medicine').join(', ')}
                  </span>
                </div>
                <ChevronRight className="h-6 w-6 shrink-0 text-[#0F6383]" aria-hidden="true" />
              </MyCard>
            </Link>
          )}
          {stopped.length > 0 && (
            <MyCard className="border-2 border-[#F2C4BF]">
              <p className="text-base font-semibold text-[#9B1C12]">
                Stopped by your care team — don't take: {stopped.map((m) => m.medication_name ?? 'Medicine').join(', ')}
              </p>
            </MyCard>
          )}

          {(otherCount > 0 || plan.data.conditions.length > 0) && (
            <Link to="/my/care" className="block">
              <MyCard className="flex items-center justify-between gap-3 hover:bg-[#FAFCFC]">
                <div className="flex flex-col gap-1">
                  <span className="text-lg font-semibold">Your care instructions</span>
                  <span className="text-base text-[#53656E]">Activity, food, wound care and more</span>
                </div>
                <ChevronRight className="h-6 w-6 shrink-0 text-[#0F6383]" aria-hidden="true" />
              </MyCard>
            </Link>
          )}
        </>
      )}

      <p className="mt-2 text-sm leading-relaxed text-[#53656E]">
        Never change a dose on your own. If something here doesn't match what you were told, ask your nurse or doctor.
        In an emergency, call 911.
      </p>
    </MyAppLayout>
  )
}

function subtitle(profile: ReturnType<typeof useMyProfile>['data']) {
  if (!profile) return undefined
  if (profile.admission_status === 'ACTIVE') return profile.room_number ? `In hospital · Room ${profile.room_number}` : 'In hospital'
  return profile.access_expires_at
    ? `At home · this app works until ${formatDate(profile.access_expires_at.slice(0, 10))}`
    : 'At home'
}
