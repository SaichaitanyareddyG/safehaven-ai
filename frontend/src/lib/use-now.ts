import { useEffect, useState } from 'react'

/** The current time, refreshed every `everyMs` — for "upcoming vs past"
 *  splits that should move on by themselves while a page stays open. */
export function useNow(everyMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(timer)
  }, [everyMs])
  return now
}
