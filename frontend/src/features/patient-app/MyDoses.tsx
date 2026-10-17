import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, BellOff, Check, Share, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

import { getPushStatus, recordDose } from '@/api/patient-app'
import { MyCard, MySectionTitle } from '@/features/patient-app/MyAppLayout'
import { type ReminderState, reminderState, turnOffReminders, turnOnReminders } from '@/features/patient-app/reminders'
import { ApiError } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { MyDose, MyDosesResponse } from '@/types/patient-app'

/** Today's doses, earliest first. At home each one gets Taken / Skip; in
 *  hospital the list is for information, because nurses give the doses. */
export function TodaysDoses({ data }: { data: MyDosesResponse }) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ dose, status }: { dose: MyDose; status: MyDose['status'] }) =>
      recordDose({ instruction_id: dose.instruction_id, date: data.date, time: dose.time, status }),
    onMutate: async ({ dose, status }) => {
      // Answer at once on screen; the server catches up.
      await queryClient.cancelQueries({ queryKey: ['my', 'doses'] })
      const previous = queryClient.getQueryData<MyDosesResponse>(['my', 'doses'])
      queryClient.setQueryData<MyDosesResponse>(['my', 'doses'], (old) =>
        old && {
          ...old,
          doses: old.doses.map((d) =>
            d.instruction_id === dose.instruction_id && d.time === dose.time ? { ...d, status } : d,
          ),
        },
      )
      return { previous }
    },
    onError: (error, _vars, context) => {
      if (context?.previous) queryClient.setQueryData(['my', 'doses'], context.previous)
      toast.error(error instanceof ApiError ? error.message : "Couldn't save that — please try again.")
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['my', 'doses'] }),
  })

  if (data.doses.length === 0) return null
  const left = data.doses.filter((d) => d.status === null).length

  return (
    <>
      <MySectionTitle>Your medicines today</MySectionTitle>
      <p className="-mt-2 text-base text-[#53656E]" data-testid="my-doses-summary">
        {!data.at_home
          ? "While you're in hospital, your nurse gives these."
          : left === 0
            ? 'All done for today.'
            : `${left} of ${data.doses.length} still to take.`}
      </p>
      <div className="flex flex-col gap-3" data-testid="my-doses-today">
        {data.doses.map((dose) => (
          <MyCard key={`${dose.instruction_id}-${dose.time}`} className="flex flex-col gap-3" data-testid="my-dose">
            <div className="flex items-start gap-4">
              <span className="min-w-[76px] text-lg font-semibold text-[#0F6383]">{dose.time_display}</span>
              <span className="flex flex-col">
                <span className="text-lg font-semibold">
                  {dose.medication_name}
                  {dose.dose ? ` ${dose.dose}` : ''}
                </span>
                {dose.with_food && <span className="text-base text-[#53656E]">With food</span>}
              </span>
            </div>
            {data.at_home && dose.status === null && (
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={() => mutation.mutate({ dose, status: 'TAKEN' })}
                  aria-label={`Mark ${dose.medication_name} ${dose.time_display} as taken`}
                  className="flex h-12 grow items-center justify-center gap-2 rounded-xl bg-[#0F6383] text-[17px] font-semibold text-white hover:bg-[#0B5068]"
                  data-testid="my-dose-taken"
                >
                  <Check className="h-5 w-5" aria-hidden="true" />
                  Taken
                </button>
                <button
                  type="button"
                  onClick={() => mutation.mutate({ dose, status: 'SKIPPED' })}
                  aria-label={`Mark ${dose.medication_name} ${dose.time_display} as skipped`}
                  className="h-12 rounded-xl border-[1.5px] border-[#C9D6DB] bg-white px-5 text-[17px] font-medium text-[#2E3A3D] hover:bg-[#F3F7F8]"
                  data-testid="my-dose-skip"
                >
                  Skip
                </button>
              </div>
            )}
            {data.at_home && dose.status !== null && (
              <div
                className={cn(
                  'flex items-center justify-between gap-2 rounded-xl px-3 py-2',
                  dose.status === 'TAKEN' ? 'bg-[#E2F0F5] text-[#0B5068]' : 'bg-[#FFF4E5] text-[#7A4200]',
                )}
              >
                <span className="flex items-center gap-2 text-base font-semibold">
                  {dose.status === 'TAKEN' ? <Check className="h-5 w-5" aria-hidden="true" /> : <X className="h-5 w-5" aria-hidden="true" />}
                  {dose.status === 'TAKEN' ? 'Taken' : 'Skipped — your care team can see this'}
                </span>
                <button
                  type="button"
                  onClick={() => mutation.mutate({ dose, status: null })}
                  aria-label={`Undo ${dose.medication_name} ${dose.time_display}`}
                  className="min-h-12 px-3 text-base font-medium text-[#0F6383]"
                  data-testid="my-dose-undo"
                >
                  Undo
                </button>
              </div>
            )}
          </MyCard>
        ))}
      </div>
    </>
  )
}

/** Turn dose reminders on or off for this phone, with the steps an iPhone
 *  needs first. Shown only when there is something to remind about. */
export function RemindersCard() {
  const push = useQuery({ queryKey: ['push-status'], queryFn: getPushStatus, staleTime: Infinity })
  const [state, setState] = useState<ReminderState | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    reminderState()
      .then((s) => alive && setState(s))
      .catch(() => alive && setState('unsupported'))
    return () => {
      alive = false
    }
  }, [])

  if (!push.data?.available || !push.data.public_key || state === null || state === 'unsupported') return null

  async function turnOn() {
    setBusy(true)
    try {
      setState(await turnOnReminders(push.data!.public_key!))
    } catch {
      toast.error("Couldn't turn on reminders. Please try again.")
    } finally {
      setBusy(false)
    }
  }

  async function turnOff() {
    setBusy(true)
    try {
      await turnOffReminders()
      setState('off')
    } finally {
      setBusy(false)
    }
  }

  return (
    <MyCard className="flex flex-col gap-3" data-testid="my-reminders" data-state={state}>
      {state === 'on' ? (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold">
            <Bell className="h-5 w-5 text-[#0F6383]" aria-hidden="true" />
            Reminders are on
          </p>
          <p className="text-base text-[#53656E]">
            This phone gets a reminder at each dose time once you're home. It never names your medicines.
          </p>
          <button type="button" disabled={busy} onClick={turnOff} className="self-start py-2 text-base font-medium text-[#0F6383]">
            Turn off reminders
          </button>
        </>
      ) : state === 'install-first' ? (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold">
            <Bell className="h-5 w-5 text-[#0F6383]" aria-hidden="true" />
            Get dose reminders on your iPhone
          </p>
          <ol className="flex list-decimal flex-col gap-1 pl-6 text-base">
            <li>
              Tap <Share className="inline h-4 w-4 align-[-2px]" aria-label="Share" /> at the bottom of Safari.
            </li>
            <li>Choose “Add to Home Screen”.</li>
            <li>Open SafeHaven from your Home Screen and turn reminders on there.</li>
          </ol>
        </>
      ) : state === 'denied' ? (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold">
            <BellOff className="h-5 w-5 text-[#53656E]" aria-hidden="true" />
            Reminders are blocked
          </p>
          <p className="text-base text-[#53656E]">
            Notifications for SafeHaven are turned off in your phone's settings. Allow them there to get reminders.
          </p>
        </>
      ) : (
        <>
          <p className="flex items-center gap-2 text-lg font-semibold">
            <Bell className="h-5 w-5 text-[#0F6383]" aria-hidden="true" />
            Never miss a dose
          </p>
          <p className="text-base text-[#53656E]">Get a reminder on this phone at each dose time once you're home.</p>
          <button
            type="button"
            disabled={busy}
            onClick={turnOn}
            className="flex h-12 items-center justify-center gap-2 rounded-xl bg-[#0F6383] text-[17px] font-semibold text-white hover:bg-[#0B5068] disabled:opacity-50"
            data-testid="my-reminders-on"
          >
            {busy ? 'Turning on…' : 'Turn on reminders'}
          </button>
        </>
      )}
    </MyCard>
  )
}
