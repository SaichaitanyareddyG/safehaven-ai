import { AlertTriangle, ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'

import { MyCard } from '@/features/patient-app/MyAppLayout'
import { courseEnded, textFor } from '@/features/patient-app/use-my-data'
import { formatDate, formatDateTime } from '@/lib/format'
import { instructionIcon, instructionTypeLabel } from '@/lib/instruction-icons'
import { textDirection } from '@/lib/language-labels'
import type { PatientAllergyView, PatientCareInstructionView } from '@/types/patient-access'
import type { MyVisit } from '@/types/patient-app'
import type { Language } from '@/types/patients'

export function MedicineCard({ medicine, language }: { medicine: PatientCareInstructionView; language: Language }) {
  const [open, setOpen] = useState(false)
  const text = textFor(medicine, language)
  const shownIn: Language = medicine.text_by_language[language] ? language : 'ENGLISH'
  return (
    <MyCard className="flex flex-col gap-3" data-testid="my-medicine-card">
      <p className="text-[21px] font-semibold">{medicine.medication_name ?? 'Medicine'}</p>
      <p className="text-lg leading-relaxed" dir={textDirection(shownIn)}>
        {text}
      </p>
      <ScheduleFacts medicine={medicine} />
      {open && medicine.why && (
        <div className="rounded-xl bg-[#F3F7F8] p-3">
          <p className="text-base font-semibold">
            {medicine.why.tier === 'DOCUMENTED' ? 'Why you take this' : 'What this medicine is generally used for'}
          </p>
          <p className="mt-1 text-base leading-relaxed">{medicine.why.text}</p>
          {medicine.why.disclaimer && <p className="mt-1 text-sm text-[#53656E]">{medicine.why.disclaimer}</p>}
        </div>
      )}
      {medicine.why && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="flex min-h-11 items-center gap-1 self-start text-base font-semibold text-[#0F6383]"
        >
          {open ? 'Show less' : 'Why I take this'}
          {open ? <ChevronUp className="h-5 w-5" aria-hidden="true" /> : <ChevronDown className="h-5 w-5" aria-hidden="true" />}
        </button>
      )}
    </MyCard>
  )
}

export function PastMedicineRow({ medicine, language }: { medicine: PatientCareInstructionView; language: Language }) {
  const stopped = medicine.past_reason === 'STOPPED'
  return (
    <div className="flex flex-col gap-1 border-b border-[#E1E8EC] py-3 last:border-b-0" data-testid="my-past-medicine">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="text-base font-semibold">{medicine.medication_name ?? 'Medicine'}</span>
        {stopped ? (
          <span className="flex items-center gap-1 text-sm font-semibold text-[#9B1C12]">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Stopped — don't take
          </span>
        ) : (
          <span className="text-sm text-[#53656E]">Course finished</span>
        )}
      </div>
      <p className="text-sm text-[#53656E]">{textFor(medicine, language)}</p>
    </div>
  )
}

export function CareInstructionCard({
  instruction,
  language,
}: {
  instruction: PatientCareInstructionView
  language: Language
}) {
  const shownIn: Language = instruction.text_by_language[language] ? language : 'ENGLISH'
  return (
    <MyCard className="flex flex-col gap-2" data-testid="my-care-instruction">
      <p className="text-lg font-semibold">
        <span aria-hidden="true">{instructionIcon(instruction.instruction_type)}</span>{' '}
        {instructionTypeLabel(instruction.instruction_type)}
      </p>
      <p className="text-lg leading-relaxed" dir={textDirection(shownIn)}>
        {textFor(instruction, language)}
      </p>
    </MyCard>
  )
}

export function AllergiesCard({ allergies }: { allergies: PatientAllergyView[] }) {
  return (
    <div className="rounded-2xl border-2 border-amber-300 bg-[#FFF4E5] p-4 text-[#5C3300]" data-testid="my-allergies">
      <p className="flex items-center gap-2 text-lg font-semibold">
        <AlertTriangle className="h-5 w-5 shrink-0" aria-hidden="true" />
        Your allergies
      </p>
      <ul className="mt-2 flex flex-col gap-1">
        {allergies.map((a, i) => (
          <li key={i} className="text-base">
            <span className="font-semibold">{a.allergen}</span>
            {(a.reaction || a.severity) && <span> — {[a.severity, a.reaction].filter(Boolean).join(', ')}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm">Something wrong or missing? Tell your nurse or doctor.</p>
    </div>
  )
}

export function CurrentStayCard({ visit, room }: { visit: MyVisit; room: string | null }) {
  const npoNow = visit.nil_by_mouth_from !== null
  return (
    <MyCard className="flex flex-col gap-3" data-testid="my-current-stay">
      <div className="flex items-center justify-between gap-2">
        <span className="text-lg font-semibold">In hospital now</span>
        <span className="rounded-full bg-[#E2F0F5] px-3 py-1 text-sm font-semibold text-[#0B5068]">Current stay</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Fact label="Admitted" value={formatDate(visit.admission_date)} />
        <Fact label="Room" value={room ?? '—'} />
      </div>
      {visit.reason_for_visit && (
        <p className="text-base leading-relaxed">
          <span className="font-semibold">Reason:</span> {visit.reason_for_visit}
        </p>
      )}
      {visit.planned_procedure && (
        <p className="text-base leading-relaxed">
          <span className="font-semibold">Planned procedure:</span> {visit.planned_procedure}
        </p>
      )}
      {npoNow && (
        <div className="flex gap-2 rounded-xl bg-[#FFF4E5] p-3 text-[#7A4200]" role="note">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />
          <span className="text-base leading-snug">
            Nothing to eat or drink from {formatDateTime(visit.nil_by_mouth_from!)}, unless your care team says
            otherwise.
          </span>
        </div>
      )}
    </MyCard>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-[#F3F7F8] px-3 py-2">
      <div className="text-xs text-[#53656E]">{label}</div>
      <div className="text-base font-medium">{value}</div>
    </div>
  )
}


/** When and until when, from the approved dose schedule. Shows nothing it
 *  cannot state exactly. */
function ScheduleFacts({ medicine }: { medicine: PatientCareInstructionView }) {
  const schedule = medicine.schedule
  if (!schedule) return null
  if (schedule.kind === 'NEEDS_REVIEW') {
    return <p className="text-base text-[#53656E]">Ask your nurse or doctor exactly when to take this.</p>
  }
  if (courseEnded(medicine)) {
    return (
      <p className="rounded-xl bg-[#FFF4E5] p-3 text-base text-[#7A4200]" data-testid="my-course-ended">
        This course ended on {formatDate(schedule.end_date!)}. Ask your care team before taking any more.
      </p>
    )
  }
  const when =
    schedule.kind === 'AS_NEEDED'
      ? 'Only when needed'
      : schedule.times_display.join(', ') + (schedule.with_food ? ', with food' : '')
  const until = schedule.end_date ? formatDate(schedule.end_date) : schedule.kind === 'AS_NEEDED' ? '—' : 'Ongoing'
  return (
    <div className="grid grid-cols-[minmax(0,3fr)_minmax(0,2fr)] gap-2" data-testid="my-medicine-schedule">
      <Fact label="When" value={when} />
      <Fact label="Until" value={until} />
    </div>
  )
}
