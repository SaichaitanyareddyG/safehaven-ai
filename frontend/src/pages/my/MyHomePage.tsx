import { ChevronRight, MessageCircle } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { AllergiesCard, CurrentStayCard } from '@/features/patient-app/MyCards'
import { RemindersCard, TodaysDoses } from '@/features/patient-app/MyDoses'
import { useMyCarePlan, useMyDoses, useMyProfile, useMyVisits } from '@/features/patient-app/use-my-data'
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
  // Only while admitted: an old visit nobody closed must never say "In hospital now" at home.
  const openVisit =
    profile.data?.admission_status === 'ACTIVE' ? visits.data?.visits.find((v) => v.status === 'OPEN') : undefined
  const medicines = plan.data?.instructions.filter((i) => i.instruction_type === 'MEDICATION') ?? []
  const otherCount = (plan.data?.instructions.length ?? 0) - medicines.length
  const doses = useMyDoses()
  const stopped = plan.data?.past_medications.filter((m) => m.past_reason === 'STOPPED') ?? []

  return (
    <MyAppLayout title={first ? `${greeting()}, ${first}` : 'Today'} subtitle={subtitle(profile.data)}>
      {(profile.isLoading || plan.isLoading) && <MyLoading />}
      {(profile.isError || plan.isError) && <MyLoadError />}

      {plan.data && plan.data.allergies.length > 0 && <AllergiesCard allergies={plan.data.allergies} />}

      {openVisit && <CurrentStayCard visit={openVisit} room={profile.data?.room_number ?? null} />}

      {plan.data && (
        <>
          {doses.data && <TodaysDoses data={doses.data} />}
          {doses.data && doses.data.doses.length > 0 && <RemindersCard />}

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

      <Link
        to="/my/ask"
        className="flex items-center gap-3 rounded-2xl bg-[#143440] p-4 text-[#E6F0F3] hover:bg-[#1A4351]"
        data-testid="my-ask-link"
      >
        <MessageCircle className="h-6 w-6 shrink-0 text-[#7CC3DB]" aria-hidden="true" />
        <span className="flex flex-col">
          <span className="text-lg font-semibold">Ask a question</span>
          <span className="text-sm text-[#9FB9C3]">About your medicines or care</span>
        </span>
      </Link>

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
