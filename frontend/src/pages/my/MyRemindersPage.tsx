import { BellRing, RefreshCw } from 'lucide-react'

import { MyAppLayout, MyCard, MyLoadError, MyLoading, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { CalendarButtons, CopyCalendarLink } from '@/features/patient-app/CalendarReminders'
import { useMyCalendar, useResetCalendar } from '@/features/patient-app/use-my-data'

/** Reminders through the phone's own calendar: added once, updated by itself. */
export function MyRemindersPage() {
  const calendar = useMyCalendar()
  const reset = useResetCalendar()

  return (
    <MyAppLayout title="Reminders" subtitle="On your phone's calendar">
      {calendar.isLoading && <MyLoading />}
      {calendar.isError && <MyLoadError />}
      {calendar.data && (
        <>
          <MyCard className="flex flex-col gap-4">
            <p className="flex items-center gap-2 text-lg font-semibold">
              <BellRing className="h-5 w-5 text-[#0F6383]" aria-hidden="true" />
              Add reminders to your calendar
            </p>
            <ul className="flex list-disc flex-col gap-1 pl-5 text-base leading-relaxed">
              <li>A reminder at each time to take your medicines, once you're home.</li>
              <li>A reminder the evening before and 2 hours before each hospital appointment.</li>
              <li>If your care team changes a medicine, your calendar updates by itself.</li>
            </ul>
            <CalendarButtons links={calendar.data} />
            <CopyCalendarLink links={calendar.data} />
          </MyCard>

          <MySectionTitle>Good to know</MySectionTitle>
          <MyCard className="flex flex-col gap-3 text-base leading-relaxed">
            <p>
              The reminders only say <strong>"Time for your medicines"</strong>. Open SafeHaven to see which ones, so
              no medicine names are stored in your calendar.
            </p>
            <p>Your phone may take a few hours to show a change. Stopping a medicine removes its reminder.</p>
            <p>
              To stop the reminders, remove the <strong>SafeHaven reminders</strong> calendar from your phone's
              calendar settings.
            </p>
          </MyCard>

          <MyCard className="flex flex-col gap-2">
            <p className="text-base font-semibold">Shared your link by mistake?</p>
            <p className="text-sm leading-relaxed text-[#53656E]">
              Make a new one. Calendars using the old link stop getting updates; add the new one again.
            </p>
            <button
              type="button"
              disabled={reset.isPending}
              onClick={() => {
                if (window.confirm('Make a new calendar link? The old one will stop updating.')) reset.mutate()
              }}
              className="flex min-h-11 items-center gap-2 self-start text-base font-semibold text-[#0F6383] disabled:opacity-50"
              data-testid="my-calendar-reset"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              Make a new link
            </button>
          </MyCard>
        </>
      )}
    </MyAppLayout>
  )
}
