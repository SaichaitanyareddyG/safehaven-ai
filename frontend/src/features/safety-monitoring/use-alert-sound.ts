import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * A short audible alert, built on the Web Audio API.
 *
 * No dependency and no audio file: two synthesised beeps are enough, and
 * adding either would break the project's no-new-dependencies rule for a
 * quarter-second of sound.
 *
 * Browsers refuse to start audio without a user gesture, so an AudioContext
 * created on page load begins suspended. Rather than hide that, the preference
 * toggle doubles as the unlock: clicking "Sound on" is itself the gesture that
 * resumes the context. If audio never unlocks, the visual toast still fires —
 * sound is an enhancement, never the only channel for an alert.
 */

const STORAGE_KEY = 'safehaven.alert_sound_enabled'

function readPreference(): boolean {
  try {
    // Default ON: this is a patient-safety queue, and a nurse who has not
    // opted out should hear a possible fall.
    return window.localStorage.getItem(STORAGE_KEY) !== 'false'
  } catch {
    return true
  }
}

function beep(ctx: AudioContext, startAt: number, frequency: number) {
  const oscillator = ctx.createOscillator()
  const gain = ctx.createGain()
  oscillator.connect(gain)
  gain.connect(ctx.destination)

  oscillator.type = 'sine'
  oscillator.frequency.value = frequency

  // Ramped rather than switched, so it reads as a chime instead of a click.
  gain.gain.setValueAtTime(0.0001, startAt)
  gain.gain.exponentialRampToValueAtTime(0.18, startAt + 0.02)
  gain.gain.exponentialRampToValueAtTime(0.0001, startAt + 0.22)

  oscillator.start(startAt)
  oscillator.stop(startAt + 0.24)
}

export function useAlertSound() {
  const [enabled, setEnabled] = useState(readPreference)
  const contextRef = useRef<AudioContext | null>(null)

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(enabled))
    } catch {
      // Private browsing or storage disabled — the preference simply will not
      // persist, which is not worth failing over.
    }
  }, [enabled])

  const getContext = useCallback((): AudioContext | null => {
    if (contextRef.current) return contextRef.current
    const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    contextRef.current = new Ctor()
    return contextRef.current
  }, [])

  const play = useCallback(() => {
    if (!enabled) return
    const ctx = getContext()
    if (!ctx) return
    // Still suspended means no gesture has happened yet; the toast carries it.
    void ctx.resume().then(() => {
      const now = ctx.currentTime
      beep(ctx, now, 880)
      beep(ctx, now + 0.3, 1046)
    }).catch(() => undefined)
  }, [enabled, getContext])

  /** Toggle, using the click itself to unlock audio. */
  const toggle = useCallback(() => {
    setEnabled((previous) => {
      const next = !previous
      if (next) {
        const ctx = getContext()
        void ctx?.resume().catch(() => undefined)
      }
      return next
    })
  }, [getContext])

  return { enabled, toggle, play }
}
