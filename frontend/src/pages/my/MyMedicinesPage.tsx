import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { MedicineCard, PastMedicineRow } from '@/features/patient-app/MyCards'
import { useMyCarePlan } from '@/features/patient-app/use-my-data'

export function MyMedicinesPage() {
  const { data, isLoading, isError } = useMyCarePlan()
  const language = data?.preferred_language ?? 'ENGLISH'
  const current = data?.instructions.filter((i) => i.instruction_type === 'MEDICATION') ?? []

  return (
    <MyAppLayout title="My medicines" subtitle="Approved by your care team">
      {isLoading && <MyLoading />}
      {isError && <MyLoadError />}
      {data && (
        <>
          <MySectionTitle>Taking now</MySectionTitle>
          {current.length === 0 && (
            <MyCard>
              <p className="text-lg text-[#53656E]">No medicines yet. They appear here once your care team approves them.</p>
            </MyCard>
          )}
          {current.map((medicine) => (
            <MedicineCard key={medicine.id} medicine={medicine} language={language} />
          ))}

          {data.past_medications.length > 0 && (
            <>
              <MySectionTitle>No longer taking</MySectionTitle>
              <MyCard className="py-1">
                {data.past_medications.map((medicine) => (
                  <PastMedicineRow key={medicine.id} medicine={medicine} language={language} />
                ))}
              </MyCard>
            </>
          )}
          <p className="text-sm leading-relaxed text-[#53656E]">
            Never change a dose yourself. Questions? Ask your nurse or doctor.
          </p>
        </>
      )}
    </MyAppLayout>
  )
}
