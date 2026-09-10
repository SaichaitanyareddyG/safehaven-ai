import { useCallback, useEffect, useRef, useState } from 'react'

import { getCarePlanAudio } from '@/api/patient-access'
import type { Language } from '@/types/patients'

// Audio is an accessibility feature, not a safety source of truth — the text
// itself remains canonical regardless of whether speech is available. This
// hook must never throw or block rendering if synthesis fails.
//
// Generated server-side (see app/tts/service.py) rather than via the
// browser's native speechSynthesis: patient devices vary wildly in which
// Telugu/Hindi voices (if any) are installed, so browser-side synthesis was
// unreliable. This always uses the same server-side neural voice regardless
// of the patient's device.
type SpeechStatus = 'idle' | 'loading' | 'speaking' | 'paused' | 'error'

interface UseSpeechResult {
  status: SpeechStatus
  play: () => void
  pause: () => void
  resume: () => void
  stop: () => void
  replay: () => void
}

export function useSpeech(text: string, language: Language, token: string): UseSpeechResult {
  const [status, setStatus] = useState<SpeechStatus>('idle')
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const objectUrlRef = useRef<string | null>(null)

  const cleanup = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.onended = null
      audioRef.current.onerror = null
      audioRef.current = null
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current)
      objectUrlRef.current = null
    }
  }, [])

  useEffect(() => cleanup, [cleanup])

  const play = useCallback(async () => {
    if (!text.trim()) return
    cleanup()
    setStatus('loading')
    try {
      const blob = await getCarePlanAudio(token, text, language)
      const url = URL.createObjectURL(blob)
      objectUrlRef.current = url

      const audio = new Audio(url)
      audio.onended = () => setStatus('idle')
      audio.onerror = () => setStatus('error')
      audioRef.current = audio

      await audio.play()
      setStatus('speaking')
    } catch {
      setStatus('error')
    }
  }, [text, language, token, cleanup])

  const pause = useCallback(() => {
    if (status !== 'speaking' || !audioRef.current) return
    audioRef.current.pause()
    setStatus('paused')
  }, [status])

  const resume = useCallback(() => {
    if (status !== 'paused' || !audioRef.current) return
    audioRef.current.play()
    setStatus('speaking')
  }, [status])

  const stop = useCallback(() => {
    cleanup()
    setStatus('idle')
  }, [cleanup])

  const replay = useCallback(() => {
    play()
  }, [play])

  return { status, play, pause, resume, stop, replay }
}
