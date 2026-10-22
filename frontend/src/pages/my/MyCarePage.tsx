import { Printer } from 'lucide-react'
import { Link } from 'react-router-dom'

import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { AllergiesCard, CareInstructionCard } from '@/features/patient-app/MyCards'
import { useMyCarePlan } from '@/features/patient-app/use-my-data'

export function MyCarePage() {
  const { data, isLoading, isError } = useMyCarePlan()
  const language = 'ENGLISH' as const // English only
  const instructions = data?.instructions.filter((i) => i.instruction_type !== 'MEDICATION') ?? []

  return (
    <MyAppLayout title="My care" subtitle="Instructions from your care team">
      {isLoading && <MyLoading />}
      {isError && <MyLoadError />}
      {data && (
        <>
          <Link
            to="/my/print"
            className="flex min-h-12 items-center justify-center gap-2 rounded-xl border-[1.5px] border-[#C9D6DB] bg-white text-base font-semibold text-[#0F6383]"
            data-testid="my-print-link"
          >
            <Printer className="h-5 w-5" aria-hidden="true" />
            Print or save my care plan as PDF
          </Link>
          {data.allergies.length > 0 && <AllergiesCard allergies={data.allergies} />}
          <MySectionTitle>Care instructions</MySectionTitle>
          {instructions.length === 0 && (
            <MyCard>
              <p className="text-lg text-[#53656E]">Nothing here yet. Instructions appear once your care team approves them.</p>
            </MyCard>
          )}
          {instructions.map((instruction) => (
            <CareInstructionCard key={instruction.id} instruction={instruction} language={language} />
          ))}

          {data.conditions.length > 0 && (
            <>
              <MySectionTitle>Understanding your health</MySectionTitle>
              {data.conditions.map((condition, index) => (
                <MyCard key={index} className="flex flex-col gap-2">
                  <p className="text-lg font-semibold">{condition.condition_name}</p>
                  {condition.explainer ? (
                    <>
                      <p className="text-base leading-relaxed">{condition.explainer.what_it_is}</p>
                      <p className="text-base leading-relaxed text-[#53656E]">{condition.explainer.how_it_develops}</p>
                    </>
                  ) : (
                    <p className="text-base text-[#53656E]">Ask your care team for more about this condition.</p>
                  )}
                </MyCard>
              ))}
            </>
          )}
        </>
      )}
    </MyAppLayout>
  )
}
