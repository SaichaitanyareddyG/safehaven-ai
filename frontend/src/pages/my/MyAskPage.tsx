import { PatientChatPanel } from '@/features/patient-chat/PatientChatPanel'
import { MyAppLayout } from '@/features/patient-app/MyAppLayout'

/** Ask about your medicines and care. Answers come only from the patient's
 *  own approved care plan; emergencies and dose changes are redirected by
 *  fixed rules before any AI (app/patient_chat/service.py). */
export function MyAskPage() {
  return (
    <MyAppLayout title="Ask a question" subtitle="About your medicines or care">
      <PatientChatPanel asPatient startOpen />
      <p className="text-sm leading-relaxed text-[#53656E]">
        This can't change your treatment. For anything urgent, call 911 or your care team.
      </p>
    </MyAppLayout>
  )
}
