/** A medicine's dose times, derived by fixed rules from the approved facts
 *  (backend app/schedules/). Never typed in, never written by the AI. */
export interface DoseSchedule {
  kind: 'SCHEDULED' | 'AS_NEEDED' | 'NEEDS_REVIEW'
  /** "08:00", hospital local time. */
  times: string[]
  /** "8:00 AM", same order as times. */
  times_display: string[]
  dose: string | null
  with_food: boolean | null
  /** null = no end date: continues until the care team stops it. */
  duration_days: number | null
  summary: string
  /** NEEDS_REVIEW only: why there are no reminders. */
  problem: string | null
  start_date: string | null
  end_date: string | null
}
