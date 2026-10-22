import { FileText, Printer } from 'lucide-react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { AllergiesCard, CareInstructionCard } from '@/features/patient-app/MyCards'
import { openReport } from '@/api/reports'
import { useMyCarePlan, useMyReports } from '@/features/patient-app/use-my-data'
import { formatDate } from '@/lib/format'
import { REPORT_CATEGORY_LABEL } from '@/types/reports'

export function MyCarePage() {
  const { data, isLoading, isError } = useMyCarePlan()
  const reports = useMyReports()
  const language = 'ENGLISH' as const // English only
  const instructions = data?.instructions.filter((i) => i.instruction_type !== 'MEDICATION') ?? []

  return (
    <MyAppLayout title="My care" subtitle="Instructions and reports from your care team">
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

          {(reports.data?.results.length ?? 0) > 0 && (
            <>
              <MySectionTitle>Your reports</MySectionTitle>
              <MyCard className="py-1" data-testid="my-reports">
                {reports.data!.results.map((r) => (
                  <button
                    key={r.id}
                    type="button"
                    className="flex min-h-14 w-full items-center gap-3 border-b border-[#E1E8EC] py-3 text-left last:border-b-0"
                    onClick={() =>
                      openReport(`/patient-app/me/reports/${r.id}/file`, true).catch(() =>
                        toast.error("Couldn't open this report. Please try again."),
                      )
                    }
                    data-testid="my-report"
                  >
                    <FileText className="h-6 w-6 shrink-0 text-[#0F6383]" aria-hidden="true" />
                    <span className="flex min-w-0 flex-col">
                      <span className="text-base font-semibold">{r.title}</span>
                      <span className="text-sm text-[#53656E]">
                        {REPORT_CATEGORY_LABEL[r.category]}
                        {r.report_date && ` · ${formatDate(r.report_date)}`}
                      </span>
                    </span>
                    <span className="ml-auto text-sm font-semibold text-[#0F6383]">Open</span>
                  </button>
                ))}
              </MyCard>
              <p className="-mt-2 text-sm text-[#53656E]">Questions about a result? Ask your care team.</p>
            </>
          )}

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
