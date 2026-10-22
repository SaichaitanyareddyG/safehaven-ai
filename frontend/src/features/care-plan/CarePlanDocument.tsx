import { ArrowLeft, Printer } from 'lucide-react'
import { format, parseISO } from 'date-fns'

import { instructionTypeLabel } from '@/lib/instruction-icons'
import type { Appointment } from '@/types/appointments'
import type { PatientCareInstructionView, PatientCarePlanResponse } from '@/types/patient-access'

export interface CarePlanDocumentProps {
  patientName: string
  dateOfBirth?: string | null
  patientCode?: string | null
  plan: PatientCarePlanResponse
  appointments: Appointment[]
  printedAt: Date
  onBack: () => void
}

const text = (i: PatientCareInstructionView) => i.text_by_language.ENGLISH ?? ''

function when(i: PatientCareInstructionView) {
  const s = i.schedule
  if (!s) return '—'
  if (s.kind === 'AS_NEEDED') return 'Only when needed'
  if (s.kind === 'NEEDS_REVIEW') return 'Ask your care team'
  return s.times_display.join(', ') + (s.with_food ? ' (with food)' : '')
}

function until(i: PatientCareInstructionView) {
  const s = i.schedule
  if (!s || s.kind !== 'SCHEDULED') return '—'
  return s.end_date ? format(parseISO(s.end_date), 'MMM d, yyyy') : 'Ongoing'
}

/** The care plan on paper (or "Save as PDF"): large type, black on white,
 *  nothing that depends on colour. Built from the same approved content
 *  the patient app shows. */
export function CarePlanDocument({
  patientName,
  dateOfBirth,
  patientCode,
  plan,
  appointments,
  printedAt,
  onBack,
}: CarePlanDocumentProps) {
  const medicines = plan.instructions.filter((i) => i.instruction_type === 'MEDICATION')
  const other = plan.instructions.filter((i) => i.instruction_type !== 'MEDICATION')
  const stopped = plan.past_medications.filter((m) => m.past_reason === 'STOPPED')

  return (
    <div className="min-h-dvh bg-[#F3F7F8] print:bg-white">
      <style>{'@page { margin: 14mm } @media print { body { background: white } }'}</style>
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-4 print:hidden">
        <button
          type="button"
          onClick={onBack}
          className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-base font-medium text-[#0F6383] hover:bg-white"
        >
          <ArrowLeft className="h-5 w-5" aria-hidden="true" />
          Back
        </button>
        <button
          type="button"
          onClick={() => window.print()}
          className="flex h-12 items-center gap-2 rounded-xl bg-[#0F6383] px-5 text-base font-semibold text-white hover:bg-[#0B5068]"
          data-testid="print-care-plan"
        >
          <Printer className="h-5 w-5" aria-hidden="true" />
          Print or save as PDF
        </button>
      </div>

      <article
        className="mx-auto max-w-3xl bg-white px-8 py-8 text-[15px] leading-relaxed text-black shadow-sm print:max-w-none print:p-0 print:shadow-none"
        data-testid="care-plan-document"
      >
        <header className="flex flex-wrap items-start justify-between gap-4 border-b-2 border-black pb-4">
          <div>
            <p className="text-xs font-semibold tracking-[0.25em]">SAFEHAVEN</p>
            <h1 className="mt-1 text-3xl font-bold">My care plan</h1>
          </div>
          <dl className="text-right text-sm">
            <div className="text-lg font-semibold">{patientName}</div>
            {dateOfBirth && <div>Date of birth: {format(parseISO(dateOfBirth), 'MMM d, yyyy')}</div>}
            {patientCode && <div>Patient number: {patientCode}</div>}
            <div>Printed: {format(printedAt, 'MMM d, yyyy, h:mm a')}</div>
          </dl>
        </header>

        {plan.allergies.length > 0 && (
          <section className="mt-6 break-inside-avoid border-2 border-black p-3">
            <h2 className="text-lg font-bold">⚠ Allergies</h2>
            <ul className="mt-1 list-disc pl-6">
              {plan.allergies.map((a, i) => (
                <li key={i}>
                  <strong>{a.allergen}</strong>
                  {(a.reaction || a.severity) && ` — ${[a.severity, a.reaction].filter(Boolean).join(', ')}`}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="mt-6">
          <h2 className="text-xl font-bold">Medicines to take</h2>
          {medicines.length === 0 ? (
            <p className="mt-1">No medicines from your care team.</p>
          ) : (
            <table className="mt-2 w-full border-collapse text-left">
              <thead>
                <tr className="border-b-2 border-black">
                  <th className="py-2 pr-3">Medicine</th>
                  <th className="py-2 pr-3">How to take it</th>
                  <th className="py-2 pr-3">When</th>
                  <th className="py-2">Until</th>
                </tr>
              </thead>
              <tbody>
                {medicines.map((m) => (
                  <tr key={m.id} className="break-inside-avoid border-b border-black/30 align-top">
                    <td className="py-2 pr-3 font-semibold">
                      {m.medication_name ?? 'Medicine'}
                      {m.schedule?.dose && <div className="font-normal">{m.schedule.dose}</div>}
                    </td>
                    <td className="py-2 pr-3">{text(m)}</td>
                    <td className="py-2 pr-3">{when(m)}</td>
                    <td className="py-2">{until(m)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {stopped.length > 0 && (
          <section className="mt-6 break-inside-avoid">
            <h2 className="text-xl font-bold">Stopped — do not take</h2>
            <ul className="mt-1 list-disc pl-6">
              {stopped.map((m) => (
                <li key={m.id}>
                  <strong>{m.medication_name ?? 'Medicine'}</strong>: your care team stopped this. Do not take any you
                  still have at home.
                </li>
              ))}
            </ul>
          </section>
        )}

        {other.length > 0 && (
          <section className="mt-6">
            <h2 className="text-xl font-bold">Care instructions</h2>
            <ul className="mt-1 space-y-2">
              {other.map((i) => (
                <li key={i.id} className="break-inside-avoid">
                  <strong>{instructionTypeLabel(i.instruction_type)}:</strong> {text(i)}
                </li>
              ))}
            </ul>
          </section>
        )}

        {appointments.length > 0 && (
          <section className="mt-6 break-inside-avoid">
            <h2 className="text-xl font-bold">Appointments</h2>
            <ul className="mt-1 space-y-1">
              {appointments.map((a) => (
                <li key={a.id}>
                  <strong>{format(new Date(a.starts_at), 'EEE, MMM d, yyyy, h:mm a')}</strong> — {a.title}
                  {a.location && `, ${a.location}`}
                  {a.notes && <div className="pl-4">{a.notes}</div>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {plan.conditions.length > 0 && (
          <section className="mt-6 break-inside-avoid">
            <h2 className="text-xl font-bold">Health conditions</h2>
            <p className="mt-1">{plan.conditions.map((c) => c.condition_name).join(', ')}</p>
          </section>
        )}

        <footer className="mt-8 break-inside-avoid border-t-2 border-black pt-3 text-sm">
          <p>
            <strong>Never change a dose on your own.</strong> Questions? Ask your nurse or doctor. In an emergency, call
            911.
          </p>
          <p className="mt-1">
            This is a copy from {format(printedAt, 'MMM d, yyyy')}. Your care team may change your plan; the SafeHaven
            app always shows the latest.
          </p>
        </footer>
      </article>
    </div>
  )
}
