import { useCallback, useEffect, useSyncExternalStore } from 'react'

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
 *
 * `speak` reads an alert aloud with the browser's built-in speech synthesis,
 * after the beeps, under the same on/off preference. Text comes from the
 * backend's alert message, so the spoken wording is the reviewed wording.
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

// One preference, one AudioContext and one "unlocked" flag for the whole app.
// The alerts page (which shows the toggle) and the app-wide notifier (which
// plays the sound) are separate components; when each kept its own copy, the
// button changed the page's copy while the notifier went on using the value it
// read at load, so "Sound on" could stay silent and "Sound off" kept beeping.
const shared = {
  enabled: readPreference(),
  unlocked: false,
  context: null as AudioContext | null,
  listeners: new Set<() => void>(),
}

function update(patch: Partial<Pick<typeof shared, 'enabled' | 'unlocked'>>) {
  Object.assign(shared, patch)
  if (patch.enabled !== undefined) {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(patch.enabled))
    } catch {
      // Private browsing or storage disabled — the preference simply will not
      // persist, which is not worth failing over.
    }
    // Muting stops speech already queued, not only the next alert.
    if (!patch.enabled && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  }
  for (const listener of shared.listeners) listener()
}

function subscribe(listener: () => void) {
  shared.listeners.add(listener)
  return () => void shared.listeners.delete(listener)
}

function getContext(): AudioContext | null {
  if (shared.context) return shared.context
  const Ctor = window.AudioContext ?? (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
  if (!Ctor) return null
  shared.context = new Ctor()
  return shared.context
}

function unlock() {
  const ctx = getContext()
  if (!ctx) return
  void ctx
    .resume()
    .then(() => {
      if (ctx.state === 'running' && !shared.unlocked) update({ unlocked: true })
    })
    .catch(() => undefined)
  // iOS also needs one utterance started from a tap before speech works later.
  if ('speechSynthesis' in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(''))
}

export function useAlertSound() {
  // Phones (iOS above all) keep audio and speech locked until the person taps
  // something on the page. Until then "Sound on" would be a promise the
  // browser won't keep, so the button says "Tap to enable sound" instead.
  const enabled = useSyncExternalStore(subscribe, () => shared.enabled)
  const unlocked = useSyncExternalStore(subscribe, () => shared.unlocked)

  // The first tap anywhere on the page unlocks audio, not only the button.
  useEffect(() => {
    if (unlocked) return
    const onFirstTap = () => unlock()
    window.addEventListener('pointerdown', onFirstTap, { once: true })
    return () => window.removeEventListener('pointerdown', onFirstTap)
  }, [unlocked])

  const play = useCallback(() => {
    if (!shared.enabled) return
    const ctx = getContext()
    if (!ctx) return
    // Still suspended means no gesture has happened yet; the toast carries it.
    void ctx.resume().then(() => {
      const now = ctx.currentTime
      beep(ctx, now, 880)
      beep(ctx, now + 0.3, 1046)
    }).catch(() => undefined)
  }, [])

  const speak = useCallback((lines: string[]) => {
    if (!shared.enabled || lines.length === 0 || !('speechSynthesis' in window)) return
    // After the two beeps, not over them; re-checked in case sound went off meanwhile.
    window.setTimeout(() => {
      if (!shared.enabled) return
      for (const line of lines) {
        const utterance = new SpeechSynthesisUtterance(line)
        utterance.rate = 0.95
        window.speechSynthesis.speak(utterance)
      }
    }, 700)
  }, [])

  /** Toggle, using the click itself to unlock audio. While still locked, a
   * tap only unlocks — it must not switch sound off. */
  const toggle = useCallback(() => {
    if (shared.enabled && !shared.unlocked) {
      unlock()
      return
    }
    const next = !shared.enabled
    if (next) unlock()
    update({ enabled: next })
  }, [])

  return { enabled, unlocked, toggle, play, speak }
}
