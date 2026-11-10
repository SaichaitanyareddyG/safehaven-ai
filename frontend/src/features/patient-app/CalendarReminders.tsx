import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CalendarPlus, Copy } from 'lucide-react'
import { toast } from 'sonner'

import { type CalendarLinks, markRemindersPrompted } from '@/api/patient-app'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { useMyCalendar } from '@/features/patient-app/use-my-data'
import { cn } from '@/lib/utils'

/** Medicine and appointment reminders through the phone's own calendar: a
 *  private feed it subscribes to once (backend app/patient_app/calendar_feed.py).
 *  Free on every phone, and it follows dose changes by itself. Entries say
 *  only "Time for your medicines", never a medicine name. */

function isApple() {
  return /iPhone|iPad|iPod|Macintosh/.test(navigator.userAgent)
}


const big =
  'flex min-h-14 w-full items-center justify-center gap-2 rounded-xl px-4 text-lg font-semibold'

/** "Add to iPhone calendar" / "Add to Google Calendar", the phone's own kind
 *  first. `onChosen` runs on either. */
export function CalendarButtons({ links, onChosen }: { links: CalendarLinks; onChosen?: () => void }) {
  const apple = (
    <a
      key="apple"
      href={links.webcal_url}
      onClick={onChosen}
      className={cn(big, isApple() ? 'bg-[#0F6383] text-white' : 'border-[1.5px] border-[#C9D6DB] bg-white text-[#0F6383]')}
      data-testid="my-calendar-apple"
    >
      <CalendarPlus className="h-5 w-5" aria-hidden="true" />
      Add to iPhone calendar
    </a>
  )
  const google = (
    <a
      key="google"
      href={links.google_url}
      target="_blank"
      rel="noreferrer"
      onClick={onChosen}
      className={cn(big, !isApple() ? 'bg-[#0F6383] text-white' : 'border-[1.5px] border-[#C9D6DB] bg-white text-[#0F6383]')}
      data-testid="my-calendar-google"
    >
      <CalendarPlus className="h-5 w-5" aria-hidden="true" />
      Add to Google Calendar
    </a>
  )
  return <div className="flex flex-col gap-3">{isApple() ? [apple, google] : [google, apple]}</div>
}

export function CopyCalendarLink({ links }: { links: CalendarLinks }) {
  return (
    <button
      type="button"
      onClick={() =>
        navigator.clipboard
          .writeText(links.feed_url)
          .then(() => toast.success('Link copied — paste it into your calendar app as a subscription'))
          .catch(() => toast.error("Couldn't copy the link"))
      }
      className="flex min-h-11 items-center gap-2 self-start text-base font-semibold text-[#0F6383]"
    >
      <Copy className="h-4 w-4" aria-hidden="true" />
      Other calendar app? Copy the link
    </button>
  )
}

/** Asked once, at first sign-in, instead of hoping the patient finds a
 *  button. Any answer — a calendar or "Not now" — counts. */
export function RemindersPrompt({ open }: { open: boolean }) {
  const queryClient = useQueryClient()
  const calendar = useMyCalendar()
  const answered = useMutation({
    mutationFn: markRemindersPrompted,
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['my', 'profile'] }),
  })
  return (
    <Dialog open={open && !answered.isSuccess} onOpenChange={(next) => !next && answered.mutate()}>
      <DialogContent className="max-w-md" data-testid="my-reminders-prompt">
        <DialogHeader>
          <DialogTitle className="text-2xl">Get reminders for your medicines?</DialogTitle>
          <DialogDescription className="text-base leading-relaxed">
            Your phone's calendar will remind you when it's time to take your medicines at home, and before hospital
            appointments. It updates by itself if your care team changes anything.
          </DialogDescription>
        </DialogHeader>
        {calendar.data ? (
          <CalendarButtons links={calendar.data} onChosen={() => answered.mutate()} />
        ) : (
          <p className="text-base text-[#53656E]">{calendar.isError ? "Couldn't load your calendar link." : 'Loading…'}</p>
        )}
        <DialogFooter>
          <button
            type="button"
            onClick={() => answered.mutate()}
            className="min-h-11 w-full text-base font-semibold text-[#53656E]"
            data-testid="my-reminders-not-now"
          >
            Not now — I can do this later in Reminders
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
